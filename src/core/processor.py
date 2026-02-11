from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from services.bgmtv import BgmtvClient, Subject
from services.openrouter import OpenRouterClient

from .models import (
    BgmCandidate,
    ConfirmStatus,
    MalInfo,
    MediaType,
    ReleaseData,
    ReleaseItem,
    StateData,
    StateItem,
)
from .season import is_new_anime, season_date_range

# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

# CJK 数字字符集
_CJK_NUMS = "一二三四五六七八九十百"

# 标题截短：后缀移除模式（按优先级排列）
_SUFFIX_PATTERNS: list[re.Pattern[str]] = [
    # 第N期 / 第N季 / 第Nクール（N 为阿拉伯或汉字数字）
    re.compile(rf"\s*第[\d{_CJK_NUMS}]+[期季]$"),
    re.compile(r"\s*第\d+クール$"),
    # Season N / Nth Season
    re.compile(r"\s+Season\s*\d+$", re.IGNORECASE),
    re.compile(r"\s+\d+(?:st|nd|rd|th)\s+Season$", re.IGNORECASE),
    # 最終章 / (新章)
    re.compile(r"\s+最終章$"),
    re.compile(r"\s*[（(]新章[）)]$"),
    # 「副标题」
    re.compile(r"\s*「[^」]+」$"),
    # ～副标题～ / 〜副标题〜
    re.compile(r"\s*～[^～]+～$"),
    re.compile(r"\s*〜[^〜]+〜$"),
    # -副标题-（含全角空格）
    re.compile(r"[\s\u3000]+-[^-]+-$"),
    # 劇場版 后缀/前缀
    re.compile(r"\s+劇場版$"),
    re.compile(r"^劇場版\s+"),
    re.compile(r"^映画\s+"),
    re.compile(r"^新劇場版\s+"),
    # N期（无「第」字，如「闇芝居 十六期」，需要前导空格以避免误匹配）
    re.compile(rf"\s+[\d{_CJK_NUMS}]+期$"),
    # 尾部数字（续集标号，如「スレイブ2」「一人之下6」）
    re.compile(r"\d+$"),
    # Part N
    re.compile(r"\s+Part\s*\d+$", re.IGNORECASE),
    # 罗马数字后缀
    re.compile(r"\s+[IVX]+$"),
]


def _normalize_title(s: str) -> str:
    """标点归一化：全角→半角，用于精确匹配比较。"""
    return unicodedata.normalize("NFKC", s).strip()


def alternative_keywords(title: str) -> list[str]:
    """从标题生成备选搜索关键词列表。

    当完整标题搜不到时，依次尝试这些关键词。
    策略：
    1. 去尾：移除已知后缀/前缀（第N期、Season N、～副标题～ 等）
    2. 去头：移除第一段（系列前缀），保留更具区分度的后半部分
       例: "機動戦士ガンダム 閃光のハサウェイ" → "閃光のハサウェイ"
    """
    results: list[str] = []
    seen: set[str] = {title}

    def _add(kw: str) -> None:
        kw = kw.strip()
        if len(kw) >= 2 and kw not in seen:
            results.append(kw)
            seen.add(kw)

    # 策略 1: 去尾 — 循环应用后缀/前缀模式
    stripped = title
    changed = True
    while changed:
        changed = False
        for pat in _SUFFIX_PATTERNS:
            new = pat.sub("", stripped).strip()
            if new != stripped and len(new) >= 2:
                stripped = new
                changed = True
                break
    _add(stripped)

    # 策略 2: 去头 — 移除第一段，保留后半部分
    for sep in (" ", "\u3000"):
        idx = title.find(sep)
        if idx >= 2:
            tail = title[idx + 1 :].strip()
            if len(tail) >= 4:
                _add(tail)
            break

    return results


def _now_iso() -> str:
    """返回当前时间的 ISO 8601 格式（带时区）。"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat(timespec="seconds")


class SeasonProcessor:
    def __init__(
        self,
        bgmtv_client: BgmtvClient,
        openrouter_client: OpenRouterClient | None = None,
    ) -> None:
        self.bgmtv = bgmtv_client
        self.openrouter = openrouter_client

    def process(self, year: int, season: str) -> None:
        """处理单个季度的新番匹配。"""
        season_key = f"{year}-{season}"
        logger.info("开始处理 {} ...", season_key)

        # 1. 加载 MAL 数据
        mal_items = self._load_mal_data(year, season)
        logger.info("MAL 条目总数: {}", len(mal_items))

        # 2. 过滤续播，只保留新番
        new_items = [item for item in mal_items if is_new_anime(item, year, season)]
        logger.info(
            "当季新番数: {} (过滤续播 {})",
            len(new_items),
            len(mal_items) - len(new_items),
        )

        # 3. 加载已有 state
        old_state = self._load_state(year, season)
        old_items_by_mal_id: dict[int, StateItem] = {}
        if old_state:
            old_items_by_mal_id = {item.mal_id: item for item in old_state.items}
            confirmed_ids = old_state.confirmed_mal_ids()
            logger.info(
                "已有 state: {} 条, 已确认: {}",
                len(old_state.items),
                len(confirmed_ids),
            )

        # 4. 遍历新番处理
        start_date, end_date = season_date_range(year, season)
        state_items: list[StateItem] = []
        stats: dict[str, int] = {}

        for raw in new_items:
            mal_id = raw["id"]

            # 已确认条目直接复用
            old_item = old_items_by_mal_id.get(mal_id)
            if old_item and old_item.status.is_confirmed():
                state_items.append(old_item)
                stats[old_item.status.value] = stats.get(old_item.status.value, 0) + 1
                continue

            # 处理新条目或未确认条目
            item = self._process_item(raw, start_date, end_date)
            state_items.append(item)
            stats[item.status.value] = stats.get(item.status.value, 0) + 1

        # 5. 保存 state
        state = StateData(
            season=season_key,
            update_time=_now_iso(),
            items=state_items,
        )
        self._save_state(year, season, state)

        # 6. 生成 release
        self._generate_release(year, season, state, mal_items)

        # 7. 打印统计
        logger.info("处理完成 {}: {}", season_key, stats)

    def _process_item(
        self,
        raw: dict[str, Any],
        start_date: str,
        end_date: str,
    ) -> StateItem:
        """处理单个 MAL 条目，执行三层匹配。"""
        mal_id = raw["id"]
        title = raw["title"]
        title_ja = raw.get("alternative_titles", {}).get("ja")
        media_type_str = raw.get("media_type", "tv")

        # 检查是否应跳过
        try:
            media_type = MediaType.from_mal(media_type_str)
            if media_type.should_skip():
                logger.debug("[skip] {} ({})", title, media_type_str)
                return StateItem(mal_id=mal_id, status=ConfirmStatus.SKIP)
        except ValueError:
            pass

        # 搜索 Bangumi
        search_keyword = title_ja or title
        logger.info("[search] {} -> keyword={}", title, search_keyword)

        try:
            subjects = self._search_bgm(search_keyword, start_date, end_date)

            # 基础搜索无结果时，用 LLM 提取关键词重试
            if not subjects and self.openrouter and search_keyword:
                suggestion = self.openrouter.suggest_search(
                    search_keyword, media_type_str
                )
                if suggestion.get("skip"):
                    logger.info("[skip] {} (LLM 判断非日本动画)", title)
                    return StateItem(mal_id=mal_id, status=ConfirmStatus.SKIP)
                for kw in suggestion.get("keywords", []):
                    logger.debug("[fallback] LLM 建议关键词: {} -> {}", title, kw)
                    subjects = self.bgmtv.search_anime_by_keyword(
                        kw, start_date, end_date
                    )
                    if subjects:
                        break
                    subjects = self.bgmtv.search_anime_by_keyword_no_date(kw)
                    if subjects:
                        break
        except Exception as e:
            logger.error("[error] {} BGM 搜索失败: {}", title, e)
            return StateItem(mal_id=mal_id, status=ConfirmStatus.ERROR)

        if not subjects:
            logger.warning("[unconfirmed] {} 无候选", title)
            return StateItem(mal_id=mal_id, status=ConfirmStatus.UNCONFIRMED)

        candidates = self._subjects_to_candidates(subjects)

        # 精确匹配：日文标题完全相等（标点归一化后比较）
        if title_ja:
            title_ja_norm = _normalize_title(title_ja)
            for subj in subjects:
                if subj.name and _normalize_title(subj.name) == title_ja_norm:
                    logger.info("[match] {} -> bgm:{} {}", title, subj.id, subj.name)
                    return StateItem(
                        mal_id=mal_id,
                        status=ConfirmStatus.MATCH,
                        bgm_id=subj.id,
                        bgm_name=subj.name,
                        bgm_name_cn=subj.name_cn,
                        candidates=candidates,
                    )

        # LLM 匹配
        if self.openrouter:
            try:
                llm_candidates = [(s.id, s.name or "", s.name_cn) for s in subjects]
                matched_id = self.openrouter.match_anime(
                    title, title_ja, llm_candidates
                )
                if matched_id is not None:
                    matched_subj = next(
                        (s for s in subjects if s.id == matched_id), None
                    )
                    if matched_subj:
                        logger.info(
                            "[model] {} -> bgm:{} {}",
                            title,
                            matched_subj.id,
                            matched_subj.name,
                        )
                        return StateItem(
                            mal_id=mal_id,
                            status=ConfirmStatus.MODEL,
                            bgm_id=matched_subj.id,
                            bgm_name=matched_subj.name,
                            bgm_name_cn=matched_subj.name_cn,
                            candidates=candidates,
                        )
            except Exception as e:
                logger.error("[error] {} LLM 匹配失败: {}", title, e)
                return StateItem(
                    mal_id=mal_id,
                    status=ConfirmStatus.ERROR,
                    candidates=candidates,
                )

        # 无匹配
        logger.warning("[unconfirmed] {} 保留 {} 个候选", title, len(candidates))
        return StateItem(
            mal_id=mal_id,
            status=ConfirmStatus.UNCONFIRMED,
            candidates=candidates,
        )

    def _search_bgm(
        self,
        keyword: str,
        start_date: str,
        end_date: str,
    ) -> list[Subject]:
        """搜索 Bangumi，包含多层回退。

        回退链：
        1. 完整关键词 + 限日期
        2. 完整关键词 + 无日期
        3. 备选关键词 + 限日期 → 无日期（逐个尝试）
        """
        # 1. 完整关键词 + 限日期
        subjects = self.bgmtv.search_anime_by_keyword(keyword, start_date, end_date)
        if subjects:
            return subjects

        # 2. 完整关键词 + 无日期
        logger.debug("[fallback] {} 限日期无结果，回退全量搜索", keyword)
        subjects = self.bgmtv.search_anime_by_keyword_no_date(keyword)
        if subjects:
            return subjects

        # 3. 备选关键词
        for alt in alternative_keywords(keyword):
            logger.debug("[fallback] 尝试备选关键词: {} -> {}", keyword, alt)
            subjects = self.bgmtv.search_anime_by_keyword(alt, start_date, end_date)
            if subjects:
                return subjects
            subjects = self.bgmtv.search_anime_by_keyword_no_date(alt)
            if subjects:
                return subjects

        return []

    def _generate_release(
        self,
        year: int,
        season: str,
        state: StateData,
        mal_items: list[dict[str, Any]],
    ) -> None:
        """从 state 生成 release 文件。"""
        mal_by_id = {item["id"]: item for item in mal_items}
        release_items: list[ReleaseItem] = []

        for si in state.items:
            if not si.status.is_confirmed():
                continue
            if si.status == ConfirmStatus.SKIP:
                continue
            if si.bgm_id is None:
                continue

            raw = mal_by_id.get(si.mal_id)
            if raw is None:
                logger.warning("MAL ID {} 在原始数据中未找到，跳过", si.mal_id)
                continue

            mal_info = MalInfo.from_raw(raw)
            release_items.append(
                ReleaseItem(
                    bgm_id=si.bgm_id,
                    bgm_name=si.bgm_name,
                    bgm_name_cn=si.bgm_name_cn,
                    mal=mal_info,
                )
            )

        # 按 bgm_id 排序
        release_items.sort(key=lambda x: x.bgm_id)

        release = ReleaseData(
            season=state.season,
            update_time=state.update_time,
            items=release_items,
        )

        release_path = ROOT_DIR / "release" / f"{year}-{season}.json"
        release_path.parent.mkdir(parents=True, exist_ok=True)
        with open(release_path, "w", encoding="utf-8") as f:
            json.dump(release.to_dict(), f, ensure_ascii=False, indent=2)
            f.write("\n")

        logger.info("release 文件已保存: {} ({} 条)", release_path, len(release_items))

    def generate_release_from_state(self, year: int, season: str) -> None:
        """从已有 state 重新生成 release（用于人工校对后更新）。"""
        state = self._load_state(year, season)
        if state is None:
            logger.error("state 文件不存在: {}-{}", year, season)
            return

        mal_items = self._load_mal_data(year, season)
        self._generate_release(year, season, state, mal_items)

    def _load_mal_data(self, year: int, season: str) -> list[dict[str, Any]]:
        """从 release/mal/ 加载 MAL 原始数据。"""
        path = ROOT_DIR / "release" / "mal" / f"{year}-{season}.json"
        if not path.exists():
            raise FileNotFoundError(f"MAL 数据文件不存在: {path}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", [])

    def _load_state(self, year: int, season: str) -> StateData | None:
        """加载已有 state 文件。"""
        path = ROOT_DIR / "state" / f"{year}-{season}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return StateData.from_dict(data)

    def _save_state(self, year: int, season: str, state: StateData) -> None:
        """保存 state 文件。"""
        path = ROOT_DIR / "state" / f"{year}-{season}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
            f.write("\n")
        logger.info("state 文件已保存: {} ({} 条)", path, len(state.items))

    @staticmethod
    def _subjects_to_candidates(subjects: list[Subject]) -> list[BgmCandidate]:
        return [
            BgmCandidate(
                bgm_id=s.id,
                bgm_name=s.name,
                bgm_name_cn=s.name_cn,
            )
            for s in subjects
        ]
