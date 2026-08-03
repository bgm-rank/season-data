"""三张拆分表的共享写入 helper。

拆表后写入边界是互斥的：fetch 只碰 mal_anime，sync-bgm 只碰 bgm_subject，
run 与人工审核只碰 season_items 的决策列。但外键要求写 season_items 之前
先落好被引用的行，这两个函数就是那道保证。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from services.bgmtv import Subject


def upsert_mal_anime(conn: sqlite3.Connection, raw: dict[str, Any], rating: str) -> None:
    """从 MAL 原始 JSON upsert 一行 mal_anime。

    rating 传的是 Rating.from_mal() 降维后的 kids/general/r18，与旧 items.mal_rating
    保持一致——发布产物直接消费这个值，不能换成 MAL 原始 rating。
    """
    alt = raw.get("alternative_titles") or {}
    start_season = raw.get("start_season") or {}
    studios = raw.get("studios")
    conn.execute(
        """
        INSERT INTO mal_anime
          (mal_id, title, title_ja, title_en, media_type, rating, start_date, end_date,
           num_episodes, source, studios, synopsis, start_season_year, start_season, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(mal_id) DO UPDATE SET
          title = excluded.title,
          title_ja = excluded.title_ja,
          title_en = excluded.title_en,
          media_type = excluded.media_type,
          rating = excluded.rating,
          start_date = excluded.start_date,
          end_date = excluded.end_date,
          num_episodes = excluded.num_episodes,
          source = excluded.source,
          studios = excluded.studios,
          synopsis = excluded.synopsis,
          start_season_year = excluded.start_season_year,
          start_season = excluded.start_season,
          fetched_at = excluded.fetched_at
        """,
        (
            raw["id"],
            raw.get("title", ""),
            alt.get("ja"),
            alt.get("en"),
            raw.get("media_type", "tv"),
            rating,
            raw.get("start_date"),
            raw.get("end_date"),
            raw.get("num_episodes"),
            raw.get("source"),
            json.dumps(studios, ensure_ascii=False) if studios else None,
            raw.get("synopsis"),
            start_season.get("year"),
            start_season.get("season"),
            datetime.now(UTC).isoformat(),
        ),
    )


def ensure_bgm_subject(conn: sqlite3.Connection, bgm_id: int, subject: Subject | None = None) -> None:
    """保证 bgm_subject 里存在 bgm_id 这一行，供 season_items.bgm_id 的外键引用。

    带 Subject 就写全字段并置 fetched_at；不带（例如 BGM API 不可用时人工填了 ID）
    就插一条 fetched_at IS NULL 的骨架行——不能让外键把人工输入卡死，骨架行
    本来就会被增量同步的待刷队列捞到。
    """
    if subject is None:
        conn.execute("INSERT OR IGNORE INTO bgm_subject (bgm_id) VALUES (?)", (bgm_id,))
        return

    conn.execute(
        """
        INSERT INTO bgm_subject
          (bgm_id, type, name, name_cn, air_date, platform, summary, tags, nsfw, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        -- 搜索结果的 Subject 比 get_subject 稀疏（可能缺 tags/summary），
        -- 用 COALESCE 保证稀疏数据不会把已经拉全的字段清成 NULL。
        ON CONFLICT(bgm_id) DO UPDATE SET
          type = COALESCE(excluded.type, bgm_subject.type),
          name = COALESCE(excluded.name, bgm_subject.name),
          name_cn = COALESCE(excluded.name_cn, bgm_subject.name_cn),
          air_date = COALESCE(excluded.air_date, bgm_subject.air_date),
          platform = COALESCE(excluded.platform, bgm_subject.platform),
          summary = COALESCE(excluded.summary, bgm_subject.summary),
          tags = COALESCE(excluded.tags, bgm_subject.tags),
          nsfw = COALESCE(excluded.nsfw, bgm_subject.nsfw),
          fetched_at = excluded.fetched_at
        """,
        (
            bgm_id,
            subject.type,
            subject.name,
            subject.name_cn,
            subject.date,
            subject.platform,
            subject.summary,
            json.dumps(subject.tags, ensure_ascii=False) if subject.tags else None,
            int(subject.nsfw) if subject.nsfw is not None else None,
            datetime.now(UTC).isoformat(),
        ),
    )
