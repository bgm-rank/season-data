"""把 season.db 里不可重建的部分导出到 data/，纳入 git 作为版本化备份。

只导决策，不导缓存：MAL 事实和 BGM 事实随时能重拉，人工审核成果不能。
- data/decisions.jsonl  每行一条 season_items 的决策，按 (season_id, mal_id) 排序，
                        git diff 是行级的——改 10 条就只有 10 行变化。
- data/meta.json        seasons 与 overrides 两张小表，凑齐恢复所需的全部输入。

用法:
  uv run python scripts/export_decisions.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "season.db"
DATA_DIR = ROOT_DIR / "data"


def main() -> None:
    if not DB_PATH.is_file():
        print(f"Error: 数据库不存在: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        decisions = conn.execute(
            """
            SELECT season_id, mal_id, status, source, bgm_id, confidence, origin
            FROM season_items
            ORDER BY season_id, mal_id
            """
        ).fetchall()
        seasons = conn.execute(
            "SELECT id, year, season, released_at, created_at, updated_at FROM seasons ORDER BY id"
        ).fetchall()
        overrides = conn.execute(
            "SELECT mal_id, season_id, action, bgm_id FROM overrides ORDER BY season_id, mal_id"
        ).fetchall()
    finally:
        conn.close()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    lines = [json.dumps(dict(r), ensure_ascii=False, sort_keys=True) for r in decisions]
    (DATA_DIR / "decisions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    meta = {
        "seasons": [dict(r) for r in seasons],
        "overrides": [dict(r) for r in overrides],
    }
    (DATA_DIR / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"导出完成: {len(decisions)} 条决策, {len(seasons)} 个季度, {len(overrides)} 条 override → {DATA_DIR}")


if __name__ == "__main__":
    main()
