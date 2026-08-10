"""override add 的落地逻辑。

`add` 的语义是「把 MAL 漏掉/错季的番插进目标季度」，但写 override 的时刻通常在**源季度**的
审查界面上。早先这个动作只把意图记进 `overrides` 表，真正插 `season_items` 要等目标季度下次跑
`run`——按倒序（2026 秋 → … → 2025 夏）审核时目标季度早已 done，永远不会再跑，于是这条番
在源季度是 excluded、在目标季度根本没有行，两边都看不见，publish 也漏掉。
（实例：MAL 61043「燃比娃」2026-08-06 从 2025-winter 改判到 2026-spring 后凭空消失。）

所以落地动作抽在这里，三个调用方共用：`SeasonProcessor.process()`、overrides 路由
（写 override 时即时落地）、`scripts/apply_pending_adds.py`（补历史欠账）。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from api.repo import ensure_bgm_subject, upsert_mal_anime
from services.bgmtv import BgmtvClient
from services.mal.client import MalClient

from .models import MalInfo


def apply_add_override(
    conn: sqlite3.Connection,
    season_id: str,
    mal_id: int,
    bgm_id: int,
    *,
    bgmtv: BgmtvClient,
    mal: MalClient | None = None,
) -> bool:
    """把一条 add override 真正插进 `season_items`（included / human / origin=override）。

    已存在该 (season_id, mal_id) 行时不动它。返回是否写入了新行。
    """
    now = datetime.now(UTC).isoformat()
    subject = bgmtv.get_subject(bgm_id)

    # MAL 拿不到时用占位，保证 mal_anime 至少有一行供外键引用
    mal_raw: dict[str, Any] = {"id": mal_id, "title": f"override-add-{mal_id}", "media_type": "tv"}
    mal_rating = "general"
    if mal is not None:
        try:
            mal_raw = mal.get_anime(mal_id)
            mal_rating = MalInfo.from_raw(mal_raw).rating
        except Exception as e:
            logger.warning("[override add] 获取 MAL 数据失败 mal:{}: {}", mal_id, e)

    upsert_mal_anime(conn, mal_raw, mal_rating)
    ensure_bgm_subject(conn, bgm_id, subject)
    cur = conn.execute(
        """
        INSERT INTO season_items
          (season_id, mal_id, status, source, bgm_id, origin, updated_at)
        VALUES (?,?,'included','human',?,'override',?)
        ON CONFLICT(season_id, mal_id) DO NOTHING
        """,
        (season_id, mal_id, bgm_id, now),
    )
    conn.commit()
    inserted = cur.rowcount > 0
    if inserted:
        logger.info("[override add] {} mal:{} -> bgm:{}", season_id, mal_id, bgm_id)
    return inserted


def pending_add_overrides(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """列出「有 add override、但目标季度还没有对应 season_items 行」的欠账。

    `bgm_id` 为空的 add 是「该挪进本季、ID 待查」的待办记录，不算欠账——补齐 ID 后才谈得上落地。
    """
    rows: list[sqlite3.Row] = conn.execute(
        """
        SELECT o.mal_id, o.season_id, o.bgm_id
        FROM overrides o
        LEFT JOIN season_items si
          ON si.season_id = o.season_id AND si.mal_id = o.mal_id
        WHERE o.action = 'add' AND o.bgm_id IS NOT NULL AND si.mal_id IS NULL
        ORDER BY o.season_id, o.mal_id
        """
    ).fetchall()
    return rows
