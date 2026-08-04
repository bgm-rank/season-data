"""全库回填 mal_anime 的扩展字段（synopsis / start_date / num_episodes / source / studios）。

003 拆表时只从旧 items 搬了 title / title_ja / media_type / rating 四项，其余列一律 NULL；
之后没重新 fetch 过的季度就一直空着（2026-08-04 实测：20607 行里只有 80 行有 start_date）。
这些字段是 high 模式 prompt 的 MAL 侧输入、也是日期硬规则的判据，空着等于那半边白做。

**只写 mal_anime 这一张缓存表**：不碰 season_items，也不新增条目——只刷新库里已有的 mal_id，
所以既不会改动季度成员，也不可能碰到人工决策。中断重跑安全（按 fetched_at 跳过已回填的季度）。

用法:
  PYTHONPATH=src uv run python scripts/backfill_mal.py                    # 全库
  PYTHONPATH=src uv run python scripts/backfill_mal.py --season 2023-fall # 只刷一季
  PYTHONPATH=src uv run python scripts/backfill_mal.py --dry-run          # 只看还差多少季
  PYTHONPATH=src uv run python scripts/backfill_mal.py --force            # 连已回填的季度一起重刷
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from api.db import get_connection  # noqa: E402
from api.repo import upsert_mal_anime  # noqa: E402
from core.models import Rating  # noqa: E402
from services.mal import MalClient  # noqa: E402


def pending_seasons(conn: sqlite3.Connection, season_id: str | None, force: bool) -> list[sqlite3.Row]:
    """待回填的季度：还有 mal_anime.fetched_at IS NULL 的条目就算。"""
    sql = """
        SELECT s.id, s.year, s.season,
               SUM(m.fetched_at IS NULL) AS stale,
               COUNT(*) AS total
        FROM seasons s
        JOIN season_items si ON si.season_id = s.id
        JOIN mal_anime m USING (mal_id)
        {where}
        GROUP BY s.id
        {having}
        ORDER BY s.id
    """.format(
        where="WHERE s.id = ?" if season_id else "",
        having="" if force else "HAVING stale > 0",
    )
    return conn.execute(sql, (season_id,) if season_id else ()).fetchall()


def backfill_season(conn: sqlite3.Connection, client: MalClient, row: sqlite3.Row) -> int:
    """回填一个季度，返回更新的行数。"""
    known: set[int] = {
        r["mal_id"] for r in conn.execute("SELECT mal_id FROM season_items WHERE season_id = ?", (row["id"],))
    }
    items = client.get_all_seasonal_anime(row["year"], row["season"])

    updated = 0
    for raw in items:
        # 只刷新库里已有的条目：新增成员是 fetch 的职责，这里不越界
        if raw["id"] not in known:
            continue
        upsert_mal_anime(conn, raw, Rating.from_mal(raw.get("rating")).value)
        updated += 1
    conn.commit()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="回填 mal_anime 扩展字段")
    parser.add_argument("--season", help="只回填该季度，如 2023-fall")
    parser.add_argument("--sleep", type=float, default=1.0, help="季度之间的间隔秒数（默认 1.0）")
    parser.add_argument("--dry-run", action="store_true", help="只打印待回填季度，不请求")
    parser.add_argument("--force", action="store_true", help="连已回填的季度一起重刷")
    args = parser.parse_args()

    load_dotenv()
    mal_client_id = os.getenv("MAL_CLIENT_ID", "")
    if not mal_client_id and not args.dry_run:
        logger.error("未设置 MAL_CLIENT_ID")
        return

    conn = get_connection()
    try:
        seasons = pending_seasons(conn, args.season, args.force)
        logger.info("待回填 {} 个季度，共 {} 条待补", len(seasons), sum(r["stale"] for r in seasons))
        if args.dry_run:
            for r in seasons:
                logger.info("  {}: {}/{} 待补", r["id"], r["stale"], r["total"])
            return
        if not seasons:
            logger.info("队列为空，无事可做")
            return

        started = time.monotonic()
        total_updated = 0
        with MalClient(mal_client_id) as client:
            for i, row in enumerate(seasons, 1):
                try:
                    updated = backfill_season(conn, client, row)
                    total_updated += updated
                    logger.info("[{}/{}] {} 回填 {} 条", i, len(seasons), row["id"], updated)
                except Exception as e:
                    logger.error("[{}/{}] {} 失败: {}", i, len(seasons), row["id"], e)
                if i < len(seasons):
                    time.sleep(args.sleep)

        logger.info("完成：更新 {} 条，耗时 {:.0f}s", total_updated, time.monotonic() - started)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
