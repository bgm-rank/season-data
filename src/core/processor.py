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
from services.openrouter import OpenRouterClient

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


def _normalize_title(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip()


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

        matched = self._try_match(mal_id, mal_title, mal_title_ja, mal_media_type, subjects, now)
        if matched:
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
                        matched = self._try_match(mal_id, mal_title, mal_title_ja, mal_media_type, retry_subjects, now)
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

    def _try_match(
        self,
        mal_id: int,
        mal_title: str,
        mal_title_ja: str | None,
        mal_media_type: str | None,
        subjects: list[Subject],
        now: str,
    ) -> bool:
        if not subjects:
            return False

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
        if self.openrouter:
            try:
                llm_candidates = [(s.id, s.name or "", s.name_cn, s.date, s.summary) for s in subjects]
                results = self.openrouter.match_anime(mal_title, mal_title_ja, mal_media_type, llm_candidates)
                if results:
                    best = results[0]
                    bgm_id_match: int = best["bgm_id"]
                    confidence: float | None = best.get("confidence")
                    matched_subj = next((s for s in subjects if s.id == bgm_id_match), None)
                    if matched_subj:
                        candidates_json = json.dumps(
                            [
                                {
                                    "bgm_id": r["bgm_id"],
                                    "bgm_name": next((s.name for s in subjects if s.id == r["bgm_id"]), None),
                                    "air_date": next((s.date for s in subjects if s.id == r["bgm_id"]), None),
                                    "confidence": r.get("confidence"),
                                }
                                for r in results
                            ],
                            ensure_ascii=False,
                        )
                        ensure_bgm_subject(self.conn, bgm_id_match, matched_subj)
                        if confidence is not None and confidence >= LLM_CONFIDENCE_THRESHOLD:
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
