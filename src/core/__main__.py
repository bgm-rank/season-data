from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from .season import SEASON_VALUES

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def _usage() -> None:
    print("Usage:")
    print("  python -m core run [--retry] <year> <season>   处理季度新番")
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


def main() -> None:
    load_dotenv()

    raw_args = sys.argv[1:]
    if not raw_args or raw_args[0] != "run":
        _usage()

    rest = raw_args[1:]

    from api.db import get_connection, init_db

    db_path = ROOT_DIR / "season.db"
    init_db(db_path)
    conn = get_connection(db_path)

    try:
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
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")

        from services.bgmtv import BgmtvClient
        from services.openrouter import (
            DEEPSEEK_BASE_URL,
            DEFAULT_DEEPSEEK_MODEL,
            DEFAULT_MODEL,
            OpenRouterClient,
        )

        from .processor import SeasonProcessor

        with BgmtvClient(bgm_token) as bgmtv:
            openrouter: OpenRouterClient | None = None
            if deepseek_key:
                model = os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
                openrouter = OpenRouterClient(deepseek_key, model=model, base_url=DEEPSEEK_BASE_URL)
            elif openrouter_key:
                model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
                openrouter = OpenRouterClient(openrouter_key, model=model)
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

    finally:
        conn.close()


if __name__ == "__main__":
    main()
