from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from loguru import logger

from services.bgmtv import BgmtvClient, Subject
from services.mal import MalClient
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

# State 子目录（按置信度分类）
_STATE_CATEGORIES = ("skip", "match", "model", "manual")

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


@dataclass
class Override:
    """override 配置。"""

    add: list[int]
    skip: list[int]


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


# manual 目录的状态别名：手动编辑时简写 → human_skip
_MANUAL_STATUS_ALIASES: dict[str, str] = {
    "s": "human_skip",
    "skip": "human_skip",
}


def _normalize_manual_statuses(data: dict[str, Any]) -> None:
    """归一化 manual 目录中的状态别名（原地修改）。"""
    for item in data.get("items", []):
        status = item.get("status", "")
        if status in _MANUAL_STATUS_ALIASES:
            item["status"] = _MANUAL_STATUS_ALIASES[status]


class SeasonProcessor:
    def __init__(
        self,
        bgmtv_client: BgmtvClient,
        openrouter_client: OpenRouterClient | None = None,
        mal_client: MalClient | None = None,
    ) -> None:
        self.bgmtv = bgmtv_client
        self.openrouter = openrouter_client
        self.mal_client = mal_client

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

        # 3. 加载 override，获取额外 MAL 数据
        override = self._load_override(year, season)
        override_skip_ids = set(override.skip)
        existing_mal_ids = {item["id"] for item in new_items}

        for mal_id in override.add:
            if mal_id in existing_mal_ids:
                logger.debug("[override] MAL {} 已在列表中，跳过", mal_id)
                continue
            if self.mal_client is None:
                logger.warning("[override] 需要 MalClient 获取 MAL {}，但未配置", mal_id)
                continue
            try:
                raw = self.mal_client.get_anime(mal_id)
                new_items.append(raw)
                existing_mal_ids.add(mal_id)
                logger.info("[override] 补番 MAL {} -> {}", mal_id, raw.get("title"))
            except Exception as e:
                logger.error("[override] 获取 MAL {} 失败: {}", mal_id, e)

        if override.add or override.skip:
            logger.info("[override] add: {}, skip: {}", len(override.add), len(override.skip))

        # 4. 加载已有 state（合并 4 个目录）
        old_items_by_mal_id = self._load_all_states(year, season)
        if old_items_by_mal_id:
            confirmed_count = sum(1 for item in old_items_by_mal_id.values() if item.status.is_confirmed())
            logger.info(
                "已有 state: {} 条, 已确认: {}",
                len(old_items_by_mal_id),
                confirmed_count,
            )

        # 5. 遍历新番处理
        start_date, end_date = season_date_range(year, season)
        state_items: list[StateItem] = []
        stats: dict[str, int] = {}

        for raw in new_items:
            mal_id = raw["id"]

            # override skip
            if mal_id in override_skip_ids:
                mal_info = MalInfo.from_raw(raw)
                logger.info("[override skip] {} (MAL {})", raw.get("title"), mal_id)
                item = StateItem(mal_id=mal_id, status=ConfirmStatus.SKIP, mal=mal_info)
                state_items.append(item)
                stats["skip"] = stats.get("skip", 0) + 1
                continue

            # 已确认条目直接复用，补充缺失的 mal 字段
            old_item = old_items_by_mal_id.get(mal_id)
            if old_item and old_item.status.is_confirmed():
                if old_item.mal is None:
                    old_item.mal = MalInfo.from_raw(raw)
                # human 状态：bgm_name 始终从 bgm_id 重新拉取，确保二次修正 bgm_id 后名称同步
                if old_item.status == ConfirmStatus.HUMAN and old_item.bgm_id is not None:
                    try:
                        subject = self.bgmtv.get_subject(old_item.bgm_id)
                        old_item.bgm_name = subject.name
                        old_item.bgm_name_cn = subject.name_cn
                        logger.debug(
                            "[human] mal:{} bgm:{} 名称已同步: {}",
                            mal_id,
                            subject.id,
                            subject.name,
                        )
                    except Exception as e:
                        logger.error(
                            "[human] mal:{} bgm:{} 获取失败: {}",
                            mal_id,
                            old_item.bgm_id,
                            e,
                        )
                state_items.append(old_item)
                stats[old_item.status.value] = stats.get(old_item.status.value, 0) + 1
                continue

            # 未确认但已手填 bgm_id → 自动补全名称并升级为 human
            if old_item and old_item.bgm_id is not None:
                if old_item.mal is None:
                    old_item.mal = MalInfo.from_raw(raw)
                if old_item.bgm_name is None:
                    try:
                        subject = self.bgmtv.get_subject(old_item.bgm_id)
                        old_item.bgm_name = subject.name
                        old_item.bgm_name_cn = subject.name_cn
                        logger.info(
                            "[auto-complete] mal:{} -> bgm:{} {}",
                            mal_id,
                            subject.id,
                            subject.name,
                        )
                    except Exception as e:
                        logger.error(
                            "[auto-complete] mal:{} bgm:{} 获取失败: {}",
                            mal_id,
                            old_item.bgm_id,
                            e,
                        )
                old_item.status = ConfirmStatus.HUMAN
                state_items.append(old_item)
                stats[old_item.status.value] = stats.get(old_item.status.value, 0) + 1
                continue

            # 处理新条目或未确认条目
            item = self._process_item(raw, start_date, end_date)
            state_items.append(item)
            stats[item.status.value] = stats.get(item.status.value, 0) + 1

        # 6. 按状态分组保存到 4 个目录
        self._save_states(year, season, state_items)

        # 7. 生成 release
        self._generate_release(year, season, state_items)

        # 8. 打印统计
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
        mal_info = MalInfo.from_raw(raw)

        # 检查是否应跳过
        try:
            media_type = MediaType.from_mal(media_type_str)
            if media_type.should_skip():
                logger.debug("[skip] {} ({})", title, media_type_str)
                return StateItem(mal_id=mal_id, status=ConfirmStatus.SKIP, mal=mal_info)
        except ValueError:
            pass

        # 搜索 + 匹配
        search_keyword = title_ja or title
        logger.info("[search] {} -> keyword={}", title, search_keyword)

        try:
            subjects = self._search_bgm(search_keyword, start_date, end_date)
        except Exception as e:
            logger.error("[error] {} BGM 搜索失败: {}", title, e)
            return StateItem(mal_id=mal_id, status=ConfirmStatus.ERROR, mal=mal_info)

        result = self._try_match(mal_id, title, title_ja, subjects, mal_info)
        if result:
            return result

        # 首轮搜索+匹配失败，用 LLM 提取关键词做最后尝试
        if self.openrouter:
            try:
                suggestion = self.openrouter.suggest_search(search_keyword, media_type_str)
                if suggestion.get("skip"):
                    logger.info("[model_skip] {} (LLM 判断非日本动画)", title)
                    return StateItem(
                        mal_id=mal_id,
                        status=ConfirmStatus.MODEL_SKIP,
                        mal=mal_info,
                    )
                for kw in suggestion.get("keywords", []):
                    logger.debug("[fallback] LLM 建议关键词: {} -> {}", title, kw)
                    retry_subjects = self.bgmtv.search_anime_by_keyword(kw, start_date, end_date)
                    if not retry_subjects:
                        retry_subjects = self.bgmtv.search_anime_by_keyword_no_date(kw)
                    if retry_subjects:
                        result = self._try_match(mal_id, title, title_ja, retry_subjects, mal_info)
                        if result:
                            return result
            except Exception as e:
                logger.error("[error] {} LLM suggest 失败: {}", title, e)

        # 全部失败 → unconfirmed
        candidates = self._subjects_to_candidates(subjects)
        logger.warning("[unconfirmed] {} 保留 {} 个候选", title, len(candidates))
        return StateItem(
            mal_id=mal_id,
            status=ConfirmStatus.UNCONFIRMED,
            mal=mal_info,
            candidates=candidates,
        )

    def _try_match(
        self,
        mal_id: int,
        title: str,
        title_ja: str | None,
        subjects: list[Subject],
        mal_info: MalInfo,
    ) -> StateItem | None:
        """尝试从搜索结果中匹配，成功返回 StateItem，失败返回 None。"""
        if not subjects:
            return None

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
                        mal=mal_info,
                        candidates=candidates,
                    )

        # LLM 匹配
        if self.openrouter:
            try:
                llm_candidates = [(s.id, s.name or "", s.name_cn) for s in subjects]
                matched_id = self.openrouter.match_anime(title, title_ja, llm_candidates)
                if matched_id is not None:
                    matched_subj = next((s for s in subjects if s.id == matched_id), None)
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
                            mal=mal_info,
                            candidates=candidates,
                        )
            except Exception as e:
                logger.error("[error] {} LLM 匹配失败: {}", title, e)

        return None

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
        items: list[StateItem],
    ) -> None:
        """从 state items 生成 release 文件。"""
        season_key = f"{year}-{season}"
        release_items: list[ReleaseItem] = []

        for si in items:
            if not si.status.is_confirmed():
                continue
            if si.status in (
                ConfirmStatus.SKIP,
                ConfirmStatus.MODEL_SKIP,
                ConfirmStatus.HUMAN_SKIP,
            ):
                continue
            if si.bgm_id is None:
                continue
            if si.mal is None:
                logger.warning("MAL ID {} 缺少 mal 信息，跳过", si.mal_id)
                continue

            release_items.append(
                ReleaseItem(
                    bgm_id=si.bgm_id,
                    bgm_name=si.bgm_name,
                    bgm_name_cn=si.bgm_name_cn,
                    mal=si.mal,
                )
            )

        # 按 bgm_id 排序
        release_items.sort(key=lambda x: x.bgm_id)

        release = ReleaseData(
            season=season_key,
            items=release_items,
        )

        release_path = ROOT_DIR / "release" / f"{year}-{season}.json"
        release_path.parent.mkdir(parents=True, exist_ok=True)
        with open(release_path, "w", encoding="utf-8") as f:
            json.dump(release.to_dict(), f, ensure_ascii=False, indent=2)
            f.write("\n")

        logger.info("release 文件已保存: {} ({} 条)", release_path, len(release_items))

    def complete_state(self, year: int, season: str) -> None:
        """自动补全 state：手动填写的 bgm_id 补全名称，更新状态，重新生成 release。

        只加载 state/manual/，处理后保存回 state/manual/，然后加载全部 state 生成 release。
        """
        manual_items = self._load_category_state(year, season, "manual")
        if not manual_items:
            logger.error("state/manual/ 文件不存在或为空: {}-{}", year, season)
            return

        updated = 0
        for item in manual_items:
            if item.bgm_id is None:
                continue
            if item.bgm_name is not None:
                continue

            # 有 bgm_id 但缺 bgm_name → 调用 API 补全
            try:
                subject = self.bgmtv.get_subject(item.bgm_id)
                item.bgm_name = subject.name
                item.bgm_name_cn = subject.name_cn
                logger.info(
                    "[complete] mal:{} -> bgm:{} {}",
                    item.mal_id,
                    subject.id,
                    subject.name,
                )
            except Exception as e:
                logger.error(
                    "[complete] mal:{} bgm:{} 获取失败: {}",
                    item.mal_id,
                    item.bgm_id,
                    e,
                )
                continue

            # unconfirmed + 已填 bgm_id → human
            if item.status == ConfirmStatus.UNCONFIRMED:
                item.status = ConfirmStatus.HUMAN
                logger.info("[complete] mal:{} 状态 unconfirmed -> human", item.mal_id)

            updated += 1

        if updated > 0:
            self._save_category_state(year, season, "manual", manual_items)
            logger.info("补全完成，更新 {} 条", updated)
        else:
            logger.info("无需补全")

        # 重新生成 release（加载全部 4 个目录）
        all_items = list(self._load_all_states(year, season).values())
        self._generate_release(year, season, all_items)

    def generate_release_from_state(self, year: int, season: str) -> None:
        """从已有 state 重新生成 release（加载全部 4 个目录）。"""
        all_items = self._load_all_states(year, season)
        if not all_items:
            logger.error("state 文件不存在: {}-{}", year, season)
            return

        self._generate_release(year, season, list(all_items.values()))

    # ---- State 读写 ----

    def _load_all_states(self, year: int, season: str) -> dict[int, StateItem]:
        """加载所有 state：合并 4 个目录的数据，按 mal_id 索引。"""
        result: dict[int, StateItem] = {}
        for category in _STATE_CATEGORIES:
            items = self._load_category_state(year, season, category)
            for item in items:
                result[item.mal_id] = item
        return result

    def _load_category_state(self, year: int, season: str, category: str) -> list[StateItem]:
        """加载单个目录的 state 文件。"""
        path = ROOT_DIR / "state" / category / f"{year}-{season}.json"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if category == "manual":
            _normalize_manual_statuses(data)
        state = StateData.from_dict(data)
        return state.items

    def _save_states(self, year: int, season: str, items: list[StateItem]) -> None:
        """按状态分组保存到 4 个目录。"""
        season_key = f"{year}-{season}"

        # 按 category 分组
        groups: dict[str, list[StateItem]] = {cat: [] for cat in _STATE_CATEGORIES}
        for item in items:
            category = item.status.status_to_category()
            groups[category].append(item)

        for category, group_items in groups.items():
            state = StateData(
                season=season_key,
                items=group_items,
            )
            path = ROOT_DIR / "state" / category / f"{year}-{season}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
                f.write("\n")
            logger.info("state/{} 已保存: {} ({} 条)", category, path.name, len(group_items))

    def _save_category_state(self, year: int, season: str, category: str, items: list[StateItem]) -> None:
        """保存单个目录的 state 文件。"""
        season_key = f"{year}-{season}"
        state = StateData(
            season=season_key,
            items=items,
        )
        path = ROOT_DIR / "state" / category / f"{year}-{season}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
            f.write("\n")
        logger.info("state/{} 已保存: {} ({} 条)", category, path.name, len(items))

    # ---- Override ----

    def _load_override(self, year: int, season: str) -> Override:
        """读取 state/override/{year}-{season}.json。"""
        path = ROOT_DIR / "state" / "override" / f"{year}-{season}.json"
        if not path.exists():
            return Override(add=[], skip=[])
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return Override(
            add=data.get("add", []),
            skip=data.get("skip", []),
        )

    # ---- MAL 数据 ----

    def _load_mal_data(self, year: int, season: str) -> list[dict[str, Any]]:
        """从 data/mal/ 加载 MAL 原始数据。"""
        path = ROOT_DIR / "data" / "mal" / f"{year}-{season}.json"
        if not path.exists():
            raise FileNotFoundError(f"MAL 数据文件不存在: {path}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cast(list[dict[str, Any]], data.get("items", []))

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
