from __future__ import annotations

import asyncio
import contextlib
import json
import re
import sqlite3
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from api.repo import ensure_bgm_subject, upsert_mal_anime
from services.bgmtv import BgmtvClient, Subject
from services.mal.client import MalClient
from services.openrouter import BgmCandidate, MalBrief, OpenRouterClient

from .models import MalInfo, MediaType
from .season import season_date_range

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

LLM_CONFIDENCE_THRESHOLD = 0.85

_CJK_NUMS = "一二三四五六七八九十百"

_SUFFIX_PATTERNS: list[re.Pattern[str]] = [
    re.compile(rf"\s*第[\d{_CJK_NUMS}]+[期季]$"),
    re.compile(r"\s*第\d+クール$"),
    re.compile(r"\s+Season\s*\d+$", re.IGNORECASE),
    re.compile(r"\s+\d+(?:st|nd|rd|th)\s+Season$", re.IGNORECASE),
    re.compile(r"\s+最終章$"),
    re.compile(r"\s*[（(]新章[）)]$"),
    re.compile(r"\s*「[^」]+」$"),
    re.compile(r"\s*～[^～]+～$"),
    re.compile(r"\s*〜[^〜]+〜$"),
    re.compile(r"[\s　]+-[^-]+-$"),
    re.compile(r"\s+劇場版$"),
    re.compile(r"^劇場版\s+"),
    re.compile(r"^映画\s+"),
    re.compile(r"^新劇場版\s+"),
    re.compile(rf"\s+[\d{_CJK_NUMS}]+期$"),
    re.compile(r"\d+$"),
    re.compile(r"\s+Part\s*\d+$", re.IGNORECASE),
    re.compile(r"\s+[IVX]+$"),
]


# 谚文（音节区 + 字母区 + 兼容字母区）与假名，用于语言护栏
_HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
_KANA_RE = re.compile(r"[぀-ヿｦ-ﾟ]")


def _normalize_title(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip()


def is_korean_title(title: str | None) -> bool:
    """谚文标题：含谚文且不含假名。

    含假名的是带韩文副标的日本动画（如「ブルーアーカイブ / 블루 아카이브」），不算。
    """
    if not title:
        return False
    return bool(_HANGUL_RE.search(title)) and not _KANA_RE.search(title)


_YM_RE = re.compile(r"^(\d{4})(?:[-/](\d{1,2}))?")

# 冲突代码，会写进 candidates JSON 的 conflicts 数组，前端据此显示 badge
CONFLICT_DATE = "date"
CONFLICT_PLATFORM = "platform"

DATE_CONFLICT_MONTHS = 6

# MAL media_type 与 BGM platform 明显互斥的组合。取值保守——platform 还有
# OVA / 动态漫画 / WEB 等一堆语义重叠的值，只挑绝无可能同指一部作品的两组。
_PLATFORM_CONFLICTS: list[tuple[set[str], set[str]]] = [
    ({"movie"}, {"TV", "WEB"}),
    ({"tv", "ona"}, {"剧场版", "劇場版"}),
]


def _parse_ym(date: str | None) -> tuple[int, int | None] | None:
    """把 `YYYY` / `YYYY-MM` / `YYYY-MM-DD` 解析成 (年, 月|None)。"""
    if not date:
        return None
    m = _YM_RE.match(date.strip())
    if not m:
        return None
    month = int(m.group(2)) if m.group(2) else None
    if month is not None and not 1 <= month <= 12:
        month = None
    return int(m.group(1)), month


def match_conflicts(mal_start_date: str | None, mal_media_type: str | None, subject: Subject) -> list[str]:
    """代码侧硬规则：LLM 说匹配、但事实明显对不上的情况。

    命中不代表一定错（MAL 拆分 / BGM 合并的边界情况确实存在），所以调用方是把
    自动 included 降级成 pending 交人工，而不是直接 excluded。
    两种 prompt 模式都跑——纯本地判断，零 token 成本，比让 LLM 自己守规则可靠。
    """
    conflicts: list[str] = []

    mal_ym = _parse_ym(mal_start_date)
    bgm_ym = _parse_ym(subject.date)
    if mal_ym and bgm_ym:
        (my, mm), (by, bm) = mal_ym, bgm_ym
        if mm is not None and bm is not None:
            if abs((my * 12 + mm) - (by * 12 + bm)) > DATE_CONFLICT_MONTHS:
                conflicts.append(CONFLICT_DATE)
        # 只精确到年时，差 1 年可能实际只差 1 个月（12 月 vs 次年 1 月），
        # 要差 2 年才能保证超过阈值。宁可漏判不误判。
        elif abs(my - by) >= 2:
            conflicts.append(CONFLICT_DATE)

    if mal_media_type and subject.platform:
        mt = mal_media_type.strip().lower()
        pf = subject.platform.strip()
        for mal_types, platforms in _PLATFORM_CONFLICTS:
            if mt in mal_types and pf in platforms:
                conflicts.append(CONFLICT_PLATFORM)
                break

    return conflicts


def alternative_keywords(title: str) -> list[str]:
    results: list[str] = []
    seen: set[str] = {title}

    def _add(kw: str) -> None:
        kw = kw.strip()
        if len(kw) >= 2 and kw not in seen:
            results.append(kw)
            seen.add(kw)

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

    for sep in (" ", "　"):
        idx = title.find(sep)
        if idx >= 2:
            tail = title[idx + 1 :].strip()
            if len(tail) >= 4:
                _add(tail)
            break

    return results


class SeasonProcessor:
    def __init__(
        self,
        conn: sqlite3.Connection,
        season_id: str,
        bgmtv_client: BgmtvClient,
        openrouter_client: OpenRouterClient | None = None,
        mal_client: MalClient | None = None,
        progress_queue: asyncio.Queue[dict[str, Any]] | None = None,
        retry: bool = False,
    ) -> None:
        self.conn = conn
        self.season_id = season_id
        self.bgmtv = bgmtv_client
        self.openrouter = openrouter_client
        self.mal = mal_client
        self.progress_queue = progress_queue
        self.retry = retry

    def _push_progress(self, event: dict[str, Any]) -> None:
        if self.progress_queue is not None:
            with contextlib.suppress(asyncio.QueueFull):
                self.progress_queue.put_nowait(event)

    def _status_dist(self) -> dict[str, int]:
        row = self.conn.execute(
            """
            SELECT
                SUM(CASE WHEN status='pending'  THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status='included' THEN 1 ELSE 0 END) AS included,
                SUM(CASE WHEN status='excluded' THEN 1 ELSE 0 END) AS excluded
            FROM season_items WHERE season_id=?
            """,
            (self.season_id,),
        ).fetchone()
        return {
            "pending": row["pending"] or 0,
            "included": row["included"] or 0,
            "excluded": row["excluded"] or 0,
        }

    def process(self) -> None:
        if self.openrouter is not None:
            logger.info("开始处理 {} (LLM prompt 模式: {}) ...", self.season_id, self.openrouter.prompt_mode)
        else:
            logger.info("开始处理 {} ...", self.season_id)

        rows = self.conn.execute("SELECT * FROM items_flat WHERE season_id=?", (self.season_id,)).fetchall()
        total = len(rows)
        processed = 0

        overrides_skip = {
            r["mal_id"]
            for r in self.conn.execute(
                "SELECT mal_id FROM overrides WHERE season_id=? AND action='skip'",
                (self.season_id,),
            ).fetchall()
        }
        overrides_add = self.conn.execute(
            "SELECT * FROM overrides WHERE season_id=? AND action='add'",
            (self.season_id,),
        ).fetchall()

        row_by_id = {r["mal_id"]: r for r in rows}
        year_str, season_str = self.season_id.split("-", 1)
        year = int(year_str)
        start_date, end_date = season_date_range(year, season_str)

        for row in rows:
            mal_id: int = row["mal_id"]
            self._process_single(row, overrides_skip, start_date, end_date)
            processed += 1
            self._push_progress(
                {
                    "type": "progress",
                    "processed": processed,
                    "total": total,
                    "status_dist": self._status_dist(),
                }
            )

        for ov_row in overrides_add:
            mal_id = ov_row["mal_id"]
            if mal_id in row_by_id:
                continue
            bgm_id_ov: int = ov_row["bgm_id"]
            now = datetime.now(UTC).isoformat()
            try:
                subject = self.bgmtv.get_subject(bgm_id_ov)

                # MAL 拿不到时用占位，保证 mal_anime 至少有一行供外键引用
                mal_raw: dict[str, Any] = {
                    "id": mal_id,
                    "title": f"override-add-{mal_id}",
                    "media_type": "tv",
                }
                mal_rating = "general"
                if self.mal is not None:
                    try:
                        mal_raw = self.mal.get_anime(mal_id)
                        mal_rating = MalInfo.from_raw(mal_raw).rating
                    except Exception as e:
                        logger.warning("[override add] 获取 MAL 数据失败 mal:{}: {}", mal_id, e)

                upsert_mal_anime(self.conn, mal_raw, mal_rating)
                ensure_bgm_subject(self.conn, bgm_id_ov, subject)
                self.conn.execute(
                    """
                    INSERT INTO season_items
                      (season_id, mal_id, status, source, bgm_id, origin, updated_at)
                    VALUES (?,?,'included','human',?,'override',?)
                    ON CONFLICT(season_id, mal_id) DO NOTHING
                    """,
                    (self.season_id, mal_id, bgm_id_ov, now),
                )
                self.conn.commit()
                logger.info("[override add] mal:{} -> bgm:{}", mal_id, bgm_id_ov)
            except Exception as e:
                logger.error("[override add] mal:{} bgm:{} 失败: {}", mal_id, bgm_id_ov, e)

        self._push_progress(
            {
                "type": "done",
                "processed": processed,
                "total": total,
                "status_dist": self._status_dist(),
            }
        )
        logger.info("处理完成 {}", self.season_id)

    def _process_single(
        self,
        row: sqlite3.Row,
        overrides_skip: set[int],
        start_date: str,
        end_date: str,
    ) -> None:
        mal_id: int = row["mal_id"]
        status: str = row["status"]
        source: str | None = row["source"]
        now = datetime.now(UTC).isoformat()

        # Step 1: override skip
        if mal_id in overrides_skip:
            self.conn.execute(
                "UPDATE season_items SET status='excluded', source='rule', updated_at=? WHERE mal_id=? AND season_id=?",
                (now, mal_id, self.season_id),
            )
            self.conn.commit()
            logger.info("[override skip] mal:{}", mal_id)
            return

        # Step 2: already confirmed (included/excluded)
        if status in ("included", "excluded"):
            if status == "included" and source == "human":
                bgm_id: int | None = row["bgm_id"]
                if bgm_id is not None:
                    # 只刷新 BGM 事实缓存，一个决策列都不碰
                    try:
                        ensure_bgm_subject(self.conn, bgm_id, self.bgmtv.get_subject(bgm_id))
                        self.conn.commit()
                    except Exception as e:
                        logger.error("[human] mal:{} bgm:{} 名称同步失败: {}", mal_id, bgm_id, e)
            return

        # Step 3: 有 bgm_id 但 subject 尚未填充 → 人工填过 ID，补全后标记 human
        bgm_id_val: int | None = row["bgm_id"]
        bgm_name_val: str | None = row["bgm_name"]
        if bgm_id_val is not None and bgm_name_val is None:
            try:
                subject = self.bgmtv.get_subject(bgm_id_val)
                ensure_bgm_subject(self.conn, bgm_id_val, subject)
                self.conn.execute(
                    "UPDATE season_items SET status='included', source='human', updated_at=?"
                    " WHERE mal_id=? AND season_id=?",
                    (now, mal_id, self.season_id),
                )
                self.conn.commit()
                logger.info("[auto-complete] mal:{} -> bgm:{} {}", mal_id, bgm_id_val, subject.name)
            except Exception as e:
                logger.error("[auto-complete] mal:{} bgm:{} 失败: {}", mal_id, bgm_id_val, e)
            return

        # Step 4: pending with source (already processed by LLM) — keep unless retry
        if status == "pending" and source is not None and not self.retry:
            return

        # Step 5: run matching
        mal_title: str = row["mal_title"]
        mal_title_ja: str | None = row["mal_title_ja"]
        mal_media_type: str = row["mal_media_type"]

        try:
            media_type = MediaType.from_mal(mal_media_type)
            if media_type.should_skip():
                self.conn.execute(
                    "UPDATE season_items SET status='excluded', source='rule', updated_at=?"
                    " WHERE mal_id=? AND season_id=?",
                    (now, mal_id, self.season_id),
                )
                self.conn.commit()
                logger.debug("[skip] mal:{} ({})", mal_id, mal_media_type)
                return
        except ValueError:
            pass

        # 语言护栏：谚文标题只信精确匹配。BGM 以谚文原名收录韩国动画，exact 分支零错误；
        # 而 LLM 对谚文候选一律给高分，是撞车主因（bgm:205216 曾被 10 条 MAL 条目占用）。
        korean = is_korean_title(mal_title_ja)

        search_keyword = mal_title_ja or mal_title
        try:
            subjects = self._search_bgm(search_keyword, start_date, end_date)
        except Exception as e:
            logger.error("[error] mal:{} BGM 搜索失败: {}", mal_id, e)
            self.conn.execute(
                "UPDATE season_items SET status='pending', source='llm', error=?, updated_at=?"
                " WHERE mal_id=? AND season_id=?",
                (str(e), now, mal_id, self.season_id),
            )
            self.conn.commit()
            return

        mal = self._mal_brief(row)
        matched = self._try_match(mal_id, mal, subjects, now, allow_llm=not korean)
        if matched:
            return

        if korean:
            self.conn.execute(
                "UPDATE season_items SET status='excluded', source='rule',"
                " candidates=NULL, error=NULL, updated_at=? WHERE mal_id=? AND season_id=?",
                (now, mal_id, self.season_id),
            )
            self.conn.commit()
            logger.info("[lang guard] mal:{} 谚文标题无精确匹配 -> excluded", mal_id)
            return

        if self.openrouter:
            try:
                suggestion = self.openrouter.suggest_search(search_keyword, mal_media_type)
                if suggestion.get("skip"):
                    self.conn.execute(
                        "UPDATE season_items SET status='excluded', source='llm', updated_at=?"
                        " WHERE mal_id=? AND season_id=?",
                        (now, mal_id, self.season_id),
                    )
                    self.conn.commit()
                    logger.info("[model_skip] mal:{}", mal_id)
                    return
                for kw in suggestion.get("keywords", []):
                    retry_subjects = self.bgmtv.search_anime_by_keyword(kw, start_date, end_date)
                    if not retry_subjects:
                        retry_subjects = self.bgmtv.search_anime_by_keyword_no_date(kw)
                    if retry_subjects:
                        matched = self._try_match(mal_id, mal, retry_subjects, now)
                        if matched:
                            return
                        subjects = subjects or retry_subjects
            except Exception as e:
                logger.error("[error] mal:{} LLM suggest 失败: {}", mal_id, e)

        candidates = [{"bgm_id": s.id, "bgm_name": s.name, "air_date": s.date, "confidence": None} for s in subjects]
        self.conn.execute(
            "UPDATE season_items SET status='pending', source=NULL,"
            " candidates=?, error=NULL, updated_at=? WHERE mal_id=? AND season_id=?",
            (json.dumps(candidates, ensure_ascii=False) if candidates else None, now, mal_id, self.season_id),
        )
        self.conn.commit()
        logger.warning("[unconfirmed] mal:{} {} 个候选", mal_id, len(candidates))

    def _mal_brief(self, row: sqlite3.Row) -> MalBrief:
        """把 items_flat 行 + mal_anime 的扩展字段拼成喂 prompt 的 MAL 侧输入。

        扩展字段不在 items_flat 视图里（视图列刻意与 ItemRead 一一对应），单独查一次。
        low 模式只有 start_date 会被用到（硬规则要），其余字段进不了 prompt。
        """
        extra = self.conn.execute(
            "SELECT start_date, num_episodes, source, studios, synopsis FROM mal_anime WHERE mal_id=?",
            (row["mal_id"],),
        ).fetchone()

        studios: list[str] | None = None
        if extra is not None and extra["studios"]:
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                studios = [s["name"] for s in json.loads(extra["studios"]) if s.get("name")] or None

        return MalBrief(
            title=row["mal_title"],
            title_ja=row["mal_title_ja"],
            media_type=row["mal_media_type"],
            start_date=extra["start_date"] if extra is not None else None,
            num_episodes=extra["num_episodes"] if extra is not None else None,
            source=extra["source"] if extra is not None else None,
            studios=studios,
            synopsis=extra["synopsis"] if extra is not None else None,
        )

    def _enrich_subjects(self, subjects: list[Subject]) -> None:
        """就地补全搜索结果缺失的字段（platform / summary / tags）。

        搜索接口不返回 platform，而 4-3 的全库同步已经把详情灌进 bgm_subject 了，
        本地查一次就能拿到——逐条 get_subject 是 10 倍 API 调用，不划算。
        只填搜索结果里为空的字段，绝不覆盖。
        """
        missing = [s.id for s in subjects if s.platform is None or s.summary is None or s.tags is None]
        if not missing:
            return

        rows = self.conn.execute(
            "SELECT bgm_id, platform, summary, tags FROM bgm_subject"
            f" WHERE fetched_at IS NOT NULL AND bgm_id IN ({','.join('?' * len(missing))})",
            missing,
        ).fetchall()
        cached = {r["bgm_id"]: r for r in rows}

        for subj in subjects:
            cache = cached.get(subj.id)
            if cache is None:
                continue
            if subj.platform is None:
                subj.platform = cache["platform"]
            if subj.summary is None:
                subj.summary = cache["summary"]
            if subj.tags is None and cache["tags"]:
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    subj.tags = json.loads(cache["tags"])

    def _try_match(
        self,
        mal_id: int,
        mal: MalBrief,
        subjects: list[Subject],
        now: str,
        allow_llm: bool = True,
    ) -> bool:
        if not subjects:
            return False

        mal_title_ja = mal.title_ja

        # Exact match
        if mal_title_ja:
            title_ja_norm = _normalize_title(mal_title_ja)
            for subj in subjects:
                if subj.name and _normalize_title(subj.name) == title_ja_norm:
                    ensure_bgm_subject(self.conn, subj.id, subj)
                    self.conn.execute(
                        "UPDATE season_items SET status='included', source='exact',"
                        " bgm_id=?, updated_at=? WHERE mal_id=? AND season_id=?",
                        (subj.id, now, mal_id, self.season_id),
                    )
                    self.conn.commit()
                    logger.info("[match] mal:{} -> bgm:{} {}", mal_id, subj.id, subj.name)
                    return True

        # LLM match
        if self.openrouter and allow_llm:
            try:
                self._enrich_subjects(subjects)
                llm_candidates = [
                    BgmCandidate(
                        bgm_id=s.id,
                        name=s.name or "",
                        name_cn=s.name_cn,
                        date=s.date,
                        summary=s.summary,
                        platform=s.platform,
                        tags=[t["name"] for t in (s.tags or []) if t.get("name")] or None,
                    )
                    for s in subjects
                ]
                results = self.openrouter.match_anime(mal, llm_candidates)
                if results:
                    best = results[0]
                    bgm_id_match: int = best["bgm_id"]
                    confidence: float | None = best.get("confidence")
                    matched_subj = next((s for s in subjects if s.id == bgm_id_match), None)
                    if matched_subj:
                        conflicts = match_conflicts(mal.start_date, mal.media_type, matched_subj)
                        candidates_json = json.dumps(
                            [
                                {
                                    "bgm_id": r["bgm_id"],
                                    "bgm_name": next((s.name for s in subjects if s.id == r["bgm_id"]), None),
                                    "air_date": next((s.date for s in subjects if s.id == r["bgm_id"]), None),
                                    "confidence": r.get("confidence"),
                                    "reason": r.get("reason"),
                                    "conflicts": conflicts if r["bgm_id"] == bgm_id_match else [],
                                }
                                for r in results
                            ],
                            ensure_ascii=False,
                        )
                        ensure_bgm_subject(self.conn, bgm_id_match, matched_subj)
                        if conflicts and confidence is not None and confidence >= LLM_CONFIDENCE_THRESHOLD:
                            logger.warning(
                                "[hard guard] mal:{} -> bgm:{} conf={} 冲突={} -> pending",
                                mal_id,
                                bgm_id_match,
                                confidence,
                                conflicts,
                            )
                        if not conflicts and confidence is not None and confidence >= LLM_CONFIDENCE_THRESHOLD:
                            self.conn.execute(
                                "UPDATE season_items SET status='included', source='llm',"
                                " bgm_id=?, confidence=?, candidates=?, updated_at=?"
                                " WHERE mal_id=? AND season_id=?",
                                (bgm_id_match, confidence, candidates_json, now, mal_id, self.season_id),
                            )
                            logger.info("[model] mal:{} -> bgm:{} conf={}", mal_id, bgm_id_match, confidence)
                        else:
                            self.conn.execute(
                                "UPDATE season_items SET status='pending', source='llm',"
                                " bgm_id=?, confidence=?, candidates=?, updated_at=?"
                                " WHERE mal_id=? AND season_id=?",
                                (bgm_id_match, confidence, candidates_json, now, mal_id, self.season_id),
                            )
                            logger.info("[model pending] mal:{} -> bgm:{} conf={}", mal_id, bgm_id_match, confidence)
                        self.conn.commit()
                        return True
            except Exception as e:
                logger.error("[error] mal:{} LLM 匹配失败: {}", mal_id, e)

        return False

    def _search_bgm(self, keyword: str, start_date: str, end_date: str) -> list[Subject]:
        subjects = self.bgmtv.search_anime_by_keyword(keyword, start_date, end_date)
        if subjects:
            return subjects

        subjects = self.bgmtv.search_anime_by_keyword_no_date(keyword)
        if subjects:
            return subjects

        for alt in alternative_keywords(keyword):
            subjects = self.bgmtv.search_anime_by_keyword(alt, start_date, end_date)
            if subjects:
                return subjects
            subjects = self.bgmtv.search_anime_by_keyword_no_date(alt)
            if subjects:
                return subjects

        return []
