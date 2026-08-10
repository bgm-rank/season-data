"""补齐「有 add override 但从未落地进 season_items」的欠账。

这类欠账是 2026-08-07 之前的历史遗留：那时 add 只写 overrides 表，真正插行要等目标季度跑 run，
而按倒序审核时目标季度早已 done，那个 run 永远不会来。现在 overrides 路由会即时落地
（见 core/overrides.py 的模块注释），本脚本用于一次性清掉存量，之后正常情况下应该跑出 0 条。

用法:
  uv run python scripts/apply_pending_adds.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from core.overrides import apply_add_override, pending_add_overrides  # noqa: E402
from services.bgmtv import BgmtvClient  # noqa: E402
from services.mal.client import MalClient  # noqa: E402

DB_PATH = ROOT / "season.db"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只列出欠账，不写库")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    rows = pending_add_overrides(conn)
    if not rows:
        print("没有待落地的 add override")
        return

    print(f"待落地 {len(rows)} 条:")
    for r in rows:
        title = conn.execute("SELECT title_ja FROM mal_anime WHERE mal_id=?", (r["mal_id"],)).fetchone()
        print(f"  {r['season_id']}  mal:{r['mal_id']}  bgm:{r['bgm_id']}  {title['title_ja'] if title else '?'}")

    if args.dry_run:
        return

    mal_client_id = os.getenv("MAL_CLIENT_ID", "")
    ok = failed = 0
    with BgmtvClient(os.getenv("BGM_TOKEN", "")) as bgmtv:
        mal = MalClient(mal_client_id) if mal_client_id else None
        try:
            for r in rows:
                try:
                    if apply_add_override(conn, r["season_id"], r["mal_id"], r["bgm_id"], bgmtv=bgmtv, mal=mal):
                        ok += 1
                except Exception as e:
                    print(f"  [失败] {r['season_id']} mal:{r['mal_id']}: {e}", file=sys.stderr)
                    failed += 1
        finally:
            if mal is not None:
                mal.close()

    print(f"\n落地 {ok} 条，失败 {failed} 条")
    if ok:
        print("记得跑 scripts/export_decisions.py 更新决策快照")


if __name__ == "__main__":
    main()
