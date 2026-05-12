"""从 data/ 目录恢复 season.db，幂等（可重复运行）。

用法:
  PYTHONPATH=src uv run python scripts/import_db.py

读取 data/*.json，将 season、items、overrides 全部 upsert 到 season.db。
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
    parser = argparse.ArgumentParser(description="从 data/ 目录恢复 season.db")
    parser.add_argument("--db", default=str(ROOT_DIR / "season.db"), help="DB 路径")
    args = parser.parse_args()

    from api.db import get_connection, init_db

    db_path = Path(args.db)
    init_db(db_path)
    conn = get_connection(db_path)

    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        print(f"data/ 目录下没有找到 JSON 文件: {DATA_DIR}", file=sys.stderr)
        sys.exit(1)

    total_items = 0
    total_overrides = 0

    try:
        for f in files:
            data = json.loads(f.read_text("utf-8"))
            season = data["season"]
            items = data.get("items", [])
            overrides = data.get("overrides", [])

            conn.execute(
                "INSERT OR REPLACE INTO seasons (id, year, season, released_at, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    season["id"],
                    season["year"],
                    season["season"],
                    season.get("released_at"),
                    season["created_at"],
                    season["updated_at"],
                ),
            )

            for item in items:
                candidates = item.get("candidates")
                conn.execute(
                    "INSERT OR REPLACE INTO items"
                    " (mal_id, season_id, status, source, confidence, bgm_id, bgm_name, bgm_name_cn,"
                    "  mal_title, mal_title_ja, mal_media_type, mal_rating, error, candidates, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item["mal_id"],
                        item["season_id"],
                        item["status"],
                        item.get("source"),
                        item.get("confidence"),
                        item.get("bgm_id"),
                        item.get("bgm_name"),
                        item.get("bgm_name_cn"),
                        item["mal_title"],
                        item.get("mal_title_ja"),
                        item["mal_media_type"],
                        item["mal_rating"],
                        item.get("error"),
                        json.dumps(candidates, ensure_ascii=False) if candidates is not None else None,
                        item["updated_at"],
                    ),
                )

            for override in overrides:
                conn.execute(
                    "INSERT OR REPLACE INTO overrides (mal_id, season_id, action, bgm_id)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        override["mal_id"],
                        override["season_id"],
                        override["action"],
                        override.get("bgm_id"),
                    ),
                )

            total_items += len(items)
            total_overrides += len(overrides)
            print(
                f"  {season['id']}: {len(items)} items, {len(overrides)} overrides",
                file=sys.stderr,
            )

        conn.commit()
        print(
            f"\n导入完成: {len(files)} 个季度，{total_items} items，{total_overrides} overrides → {db_path}",
            file=sys.stderr,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
