"""全库增量同步 BGM 条目详情。

待刷队列 = bgm_subject 里 fetched_at IS NULL 的骨架行。拉完就置 fetched_at，
中断重跑只会捡剩下的，随时 Ctrl-C 都安全。

刻意做成 CLI 而不是 API 端点：全库一万多条要跑一两个小时，而 API 进程里
主线程和 executor 共用同一个 sqlite Connection，把那个跨线程窗口拉到小时级
不值得冒险；uvicorn --reload 一保存文件也会直接杀掉任务。

用法:
  PYTHONPATH=src uv run python scripts/sync_bgm.py                    # 全库
  PYTHONPATH=src uv run python scripts/sync_bgm.py --season 2023-fall # 只刷一季
  PYTHONPATH=src uv run python scripts/sync_bgm.py --limit 50         # 先探个路
  PYTHONPATH=src uv run python scripts/sync_bgm.py --dry-run          # 只看队列多长
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from api.db import get_connection  # noqa: E402
from core.bgm_sync import pending_bgm_ids, sync_subjects  # noqa: E402

LOG_EVERY = 50


def main() -> None:
    parser = argparse.ArgumentParser(description="增量同步 BGM 条目详情")
    parser.add_argument("--season", help="只同步该季度引用到的条目，如 2023-fall")
    parser.add_argument("--limit", type=int, help="本次最多同步多少条")
    parser.add_argument("--sleep", type=float, default=0.3, help="每条之间的间隔秒数（默认 0.3）")
    parser.add_argument("--dry-run", action="store_true", help="只打印待刷数量，不请求")
    args = parser.parse_args()

    load_dotenv()

    # 自开连接，与 API 进程互不干扰：WAL 单写者，每条一 commit 只持锁毫秒级
    conn = get_connection()
    try:
        bgm_ids = pending_bgm_ids(conn, args.season)
        scope = f"季度 {args.season}" if args.season else "全库"
        logger.info("{} 待同步 {} 条", scope, len(bgm_ids))

        if args.limit is not None:
            bgm_ids = bgm_ids[: args.limit]
            logger.info("按 --limit 截取到 {} 条", len(bgm_ids))
        if args.dry_run:
            logger.info("--dry-run，不发请求")
            return
        if not bgm_ids:
            logger.info("队列为空，无事可做")
            return

        started = time.monotonic()

        def on_progress(done: int, total: int) -> None:
            if done % LOG_EVERY and done != total:
                return
            elapsed = time.monotonic() - started
            eta = elapsed / done * (total - done)
            logger.info("进度 {}/{}，已用 {:.0f}s，预计还需 {:.0f}s", done, total, elapsed, eta)

        updated, failed = sync_subjects(conn, bgm_ids, sleep=args.sleep, on_progress=on_progress)

        logger.info("完成：成功 {} 条，失败 {} 条，耗时 {:.0f}s", updated, len(failed), time.monotonic() - started)
        if failed:
            # 这些多半是 BGM 侧已删除的条目（404），fetched_at 仍是 NULL，
            # 下次重跑还会再试一遍。数量大了再考虑加 fetch_error 列记账。
            logger.warning("失败的 bgm_id: {}", ", ".join(str(i) for i in failed))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
