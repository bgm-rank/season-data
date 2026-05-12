"""将 season.db 全量导出到 data/ 目录，每个季度一个 JSON 文件。

用法:
  PYTHONPATH=src uv run python scripts/export_db.py

输出目录: data/{year}-{season}.json
每个文件包含该季度的 season 行、所有 items 及 overrides。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

sys.path.insert(0, str(ROOT_DIR / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 season.db 到 data/ 目录")
    parser.add_argument("--db", default=str(ROOT_DIR / "season.db"), help="DB 路径")
    args = parser.parse_args()

    from api.db import get_connection, init_db

    db_path = Path(args.db)
    init_db(db_path)
    conn = get_connection(db_path)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        seasons = conn.execute("SELECT * FROM seasons ORDER BY year, season").fetchall()
        if not seasons:
            print("DB 中没有季度数据", file=sys.stderr)
            return

        for season_row in seasons:
            season_id: str = season_row["id"]

            season_data = {
                "id": season_row["id"],
                "year": season_row["year"],
                "season": season_row["season"],
                "released_at": season_row["released_at"],
                "created_at": season_row["created_at"],
                "updated_at": season_row["updated_at"],
            }

            item_rows = conn.execute(
                "SELECT * FROM items WHERE season_id=? ORDER BY mal_id", (season_id,)
            ).fetchall()
            items = []
            for r in item_rows:
                candidates_raw = r["candidates"]
                items.append(
                    {
                        "mal_id": r["mal_id"],
                        "season_id": r["season_id"],
                        "status": r["status"],
                        "source": r["source"],
                        "confidence": r["confidence"],
                        "bgm_id": r["bgm_id"],
                        "bgm_name": r["bgm_name"],
                        "bgm_name_cn": r["bgm_name_cn"],
                        "mal_title": r["mal_title"],
                        "mal_title_ja": r["mal_title_ja"],
                        "mal_media_type": r["mal_media_type"],
                        "mal_rating": r["mal_rating"],
                        "error": r["error"],
                        "candidates": json.loads(candidates_raw) if candidates_raw else None,
                        "updated_at": r["updated_at"],
                    }
                )

            override_rows = conn.execute(
                "SELECT * FROM overrides WHERE season_id=? ORDER BY mal_id", (season_id,)
            ).fetchall()
            overrides = [
                {
                    "mal_id": r["mal_id"],
                    "season_id": r["season_id"],
                    "action": r["action"],
                    "bgm_id": r["bgm_id"],
                }
                for r in override_rows
            ]

            out_path = DATA_DIR / f"{season_id}.json"
            out_path.write_text(
                json.dumps(
                    {"season": season_data, "items": items, "overrides": overrides},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            print(f"  {season_id}: {len(items)} items, {len(overrides)} overrides", file=sys.stderr)

        print(f"\n导出完成: {len(seasons)} 个季度 → {DATA_DIR}", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
