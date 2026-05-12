from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from .season import SEASON_VALUES

COMMANDS = ("run", "release", "export")
ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def _usage() -> None:
    print("Usage:")
    print("  python -m core run [--retry] <year> <season>   处理季度新番")
    print("  python -m core release <year> <season>          从 DB 生成 release")
    print("  python -m core export <year> <season>           导出完整快照")
    print()
    print(f"  season: {', '.join(SEASON_VALUES)}")
    sys.exit(1)


def _parse_run_args(args: list[str]) -> tuple[bool, int, str]:
    retry = False
    if "--retry" in args:
        args = [a for a in args if a != "--retry"]
        retry = True
    if len(args) != 2:
        _usage()
    try:
        year = int(args[0])
    except ValueError:
        print(f"Error: invalid year '{args[0]}'")
        sys.exit(1)
    season = args[1]
    if season not in SEASON_VALUES:
        print(f"Error: invalid season '{season}'")
        sys.exit(1)
    return retry, year, season


def _parse_year_season(args: list[str]) -> tuple[int, str]:
    if len(args) != 2:
        _usage()
    try:
        year = int(args[0])
    except ValueError:
        print(f"Error: invalid year '{args[0]}'")
        sys.exit(1)
    season = args[1]
    if season not in SEASON_VALUES:
        print(f"Error: invalid season '{season}'")
        sys.exit(1)
    return year, season


def main() -> None:
    load_dotenv()

    raw_args = sys.argv[1:]
    if not raw_args or raw_args[0] not in COMMANDS:
        _usage()

    command = raw_args[0]
    rest = raw_args[1:]

    from api.db import get_connection, init_db

    db_path = ROOT_DIR / "season.db"
    init_db(db_path)
    conn = get_connection(db_path)

    try:
        if command == "run":
            retry, year, season = _parse_run_args(list(rest))
            season_id = f"{year}-{season}"

            row = conn.execute("SELECT 1 FROM seasons WHERE id=?", (season_id,)).fetchone()
            if row is None:
                now = datetime.now(UTC).isoformat()
                conn.execute(
                    "INSERT INTO seasons"
                    " (id, year, season, released_at, created_at, updated_at)"
                    " VALUES (?,?,?,NULL,?,?)",
                    (season_id, year, season, now, now),
                )
                conn.commit()

            bgm_token = os.getenv("BGM_TOKEN", "")
            openrouter_key = os.getenv("OPENROUTER_API_KEY", "")

            from services.bgmtv import BgmtvClient
            from services.openrouter import OpenRouterClient

            from .processor import SeasonProcessor

            with BgmtvClient(bgm_token) as bgmtv:
                openrouter: OpenRouterClient | None = None
                if openrouter_key:
                    openrouter = OpenRouterClient(openrouter_key)
                try:
                    processor = SeasonProcessor(
                        conn=conn,
                        season_id=season_id,
                        bgmtv_client=bgmtv,
                        openrouter_client=openrouter,
                        retry=retry,
                    )
                    processor.process()
                finally:
                    if openrouter:
                        openrouter.close()

        elif command == "release":
            year, season = _parse_year_season(list(rest))
            season_id = f"{year}-{season}"

            from .processor import generate_release_from_db

            generate_release_from_db(conn, season_id)

        elif command == "export":
            year, season = _parse_year_season(list(rest))
            season_id = f"{year}-{season}"

            rows = conn.execute("SELECT * FROM items WHERE season_id=?", (season_id,)).fetchall()
            items = []
            for r in rows:
                candidates_raw = r["candidates"]
                item = {
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
                items.append(item)

            today = datetime.now(UTC).strftime("%Y%m%d")
            snapshots_dir = ROOT_DIR / "snapshots"
            snapshots_dir.mkdir(parents=True, exist_ok=True)
            out_path = snapshots_dir / f"{season_id}-{today}.json"
            out_path.write_text(
                json.dumps({"season": season_id, "items": items}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"快照已保存: {out_path} ({len(items)} 条)", file=sys.stderr)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
