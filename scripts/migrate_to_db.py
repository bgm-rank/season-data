#!/usr/bin/env python3
"""迁移旧 state/ JSON 文件到 SQLite。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from api.db import get_connection, init_db

STATE_DIR = ROOT_DIR / "state"
CATEGORIES = ("skip", "match", "model", "manual")

STATUS_MIGRATION_MAP: dict[str, tuple[str, str | None]] = {
    "skip": ("excluded", "rule"),
    "match": ("included", "exact"),
    "model": ("included", "llm"),
    "model_skip": ("excluded", "llm"),
    "human": ("included", "human"),
    "human_skip": ("excluded", "human"),
    "unconfirmed": ("pending", None),
    "error": ("pending", None),
    # aliases from manual editing
    "s": ("excluded", "human"),
}

_MANUAL_STATUS_ALIASES: dict[str, str] = {
    "s": "human_skip",
    "skip": "human_skip",
}


def _normalize_status(status: str) -> str:
    return _MANUAL_STATUS_ALIASES.get(status, status)


def _season_from_filename(filename: str) -> str | None:
    """Extract season_id from filename like '2025-spring.json'."""
    m = re.match(r"^(\d{4}-(?:winter|spring|summer|fall))\.json$", filename)
    return m.group(1) if m else None


def migrate_items(conn: object, season_filter: str | None = None) -> dict[str, int]:
    """Migrate all state JSON items to DB. Returns {season_id: count}."""
    import sqlite3

    conn_typed: sqlite3.Connection = conn  # type: ignore[assignment]
    counts: dict[str, int] = {}
    now = datetime.now(UTC).isoformat()

    for category in CATEGORIES:
        cat_dir = STATE_DIR / category
        if not cat_dir.exists():
            continue

        for json_file in sorted(cat_dir.glob("*.json")):
            season_id = _season_from_filename(json_file.name)
            if season_id is None:
                continue
            if season_filter and season_id != season_filter:
                continue

            # Ensure season row exists
            if not conn_typed.execute("SELECT 1 FROM seasons WHERE id=?", (season_id,)).fetchone():
                year_str, season_str = season_id.split("-", 1)
                conn_typed.execute(
                    "INSERT OR IGNORE INTO seasons (id, year, season, released_at, created_at, updated_at) VALUES (?,?,?,NULL,?,?)",
                    (season_id, int(year_str), season_str, now, now),
                )

            data = json.loads(json_file.read_text(encoding="utf-8"))
            items = data.get("items", [])

            for item in items:
                raw_status = item.get("status", "unconfirmed")
                if category == "manual":
                    raw_status = _normalize_status(raw_status)
                status, source = STATUS_MIGRATION_MAP.get(raw_status, ("pending", None))

                mal_id: int = item["mal_id"]
                bgm_id: int | None = item.get("bgm_id")
                bgm_name: str | None = item.get("bgm_name")
                bgm_name_cn: str | None = item.get("bgm_name_cn")

                mal = item.get("mal") or {}
                mal_title: str = mal.get("title", "")
                mal_title_ja: str | None = mal.get("title_ja")
                mal_media_type: str = mal.get("media_type", "tv")
                mal_rating: str = mal.get("rating", "general")

                raw_candidates = item.get("candidates")
                candidates_json: str | None = None
                if raw_candidates:
                    cands = [
                        {
                            "bgm_id": c.get("bgm_id"),
                            "bgm_name": c.get("bgm_name"),
                            "confidence": None,
                        }
                        for c in raw_candidates
                    ]
                    candidates_json = json.dumps(cands, ensure_ascii=False)

                conn_typed.execute(
                    """
                    INSERT OR REPLACE INTO items
                      (mal_id, season_id, status, source, confidence, bgm_id, bgm_name, bgm_name_cn,
                       mal_title, mal_title_ja, mal_media_type, mal_rating, error, candidates, updated_at)
                    VALUES (?,?,?,?,NULL,?,?,?,?,?,?,?,NULL,?,?)
                    """,
                    (
                        mal_id, season_id, status, source,
                        bgm_id, bgm_name, bgm_name_cn,
                        mal_title, mal_title_ja, mal_media_type, mal_rating,
                        candidates_json, now,
                    ),
                )
                counts[season_id] = counts.get(season_id, 0) + 1

    conn_typed.commit()
    return counts


def migrate_overrides(conn: object, season_filter: str | None = None) -> dict[str, int]:
    """Migrate override JSON files to DB."""
    import sqlite3

    conn_typed: sqlite3.Connection = conn  # type: ignore[assignment]
    override_dir = STATE_DIR / "override"
    counts: dict[str, int] = {}
    now = datetime.now(UTC).isoformat()

    if not override_dir.exists():
        return counts

    for json_file in sorted(override_dir.glob("*.json")):
        season_id = _season_from_filename(json_file.name)
        if season_id is None:
            continue
        if season_filter and season_id != season_filter:
            continue

        if not conn_typed.execute("SELECT 1 FROM seasons WHERE id=?", (season_id,)).fetchone():
            year_str, season_str = season_id.split("-", 1)
            conn_typed.execute(
                "INSERT OR IGNORE INTO seasons (id, year, season, released_at, created_at, updated_at) VALUES (?,?,?,NULL,?,?)",
                (season_id, int(year_str), season_str, now, now),
            )

        data = json.loads(json_file.read_text(encoding="utf-8"))
        n = 0
        for mal_id in data.get("skip", []):
            conn_typed.execute(
                "INSERT OR REPLACE INTO overrides (mal_id, season_id, action, bgm_id) VALUES (?,?,'skip',NULL)",
                (mal_id, season_id),
            )
            n += 1
        for entry in data.get("add", []):
            if isinstance(entry, dict):
                mal_id = entry.get("mal_id")
                bgm_id = entry.get("bgm_id")
            else:
                mal_id = entry
                bgm_id = None
            conn_typed.execute(
                "INSERT OR REPLACE INTO overrides (mal_id, season_id, action, bgm_id) VALUES (?,?,'add',?)",
                (mal_id, season_id, bgm_id),
            )
            n += 1
        counts[season_id] = n

    conn_typed.commit()
    return counts


def verify_migration(conn: object, item_counts: dict[str, int]) -> bool:
    """Verify that DB row counts match original JSON counts."""
    import sqlite3

    conn_typed: sqlite3.Connection = conn  # type: ignore[assignment]
    print("\n迁移验证:")
    print(f"{'季度':<20} {'原始条目':>10} {'DB 条目':>10} {'状态':>8}")
    print("-" * 52)

    ok = True
    for season_id in sorted(item_counts.keys()):
        original = item_counts[season_id]
        db_count = conn_typed.execute(
            "SELECT COUNT(*) FROM items WHERE season_id=?", (season_id,)
        ).fetchone()[0]
        status = "✓" if db_count == original else "✗ DIFF"
        if db_count != original:
            ok = False
        print(f"{season_id:<20} {original:>10} {db_count:>10} {status:>8}")

    print()
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移 state/ JSON 到 SQLite")
    parser.add_argument("--season", help="只迁移指定季度，格式: {year}-{season}")
    args = parser.parse_args()

    db_path = ROOT_DIR / "season.db"
    init_db(db_path)
    conn = get_connection(db_path)

    try:
        print("迁移条目数据...")
        item_counts = migrate_items(conn, args.season)
        total_items = sum(item_counts.values())
        print(f"  迁移 {len(item_counts)} 个季度，共 {total_items} 条条目")

        print("迁移 override 数据...")
        override_counts = migrate_overrides(conn, args.season)
        total_overrides = sum(override_counts.values())
        print(f"  迁移 {len(override_counts)} 个季度，共 {total_overrides} 条 override")

        ok = verify_migration(conn, item_counts)
        if not ok:
            print("错误: 迁移验证失败，存在数量不一致", file=sys.stderr)
            sys.exit(1)
        else:
            print("迁移验证通过")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
