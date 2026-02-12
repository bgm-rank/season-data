from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from services.bgmtv import BgmtvClient
from services.mal import MalClient
from services.openrouter import OpenRouterClient

from .processor import SeasonProcessor
from .season import SEASON_VALUES


COMMANDS = ("run", "release", "complete")


def _usage() -> None:
    print("Usage:")
    print("  python -m core run <year> <season>      处理季度新番")
    print("  python -m core release <year> <season>   从 state 重新生成 release")
    print(
        "  python -m core complete <year> <season>  补全 bgm_id 名称并重新生成 release"
    )
    print()
    print(f"  season: {', '.join(SEASON_VALUES)}")
    sys.exit(1)


def _parse_args() -> tuple[str, int, str]:
    args = sys.argv[1:]
    if len(args) != 3:
        _usage()

    command = args[0]
    if command not in COMMANDS:
        _usage()

    try:
        year = int(args[1])
    except ValueError:
        print(f"Error: invalid year '{args[1]}'")
        sys.exit(1)

    season = args[2]
    if season not in SEASON_VALUES:
        print(f"Error: invalid season '{season}', must be one of {SEASON_VALUES}")
        sys.exit(1)

    return command, year, season


def main() -> None:
    load_dotenv()

    command, year, season = _parse_args()

    bgm_token = os.getenv("BGM_TOKEN", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    mal_client_id = os.getenv("MAL_CLIENT_ID", "")

    with BgmtvClient(bgm_token) as bgmtv:
        openrouter: OpenRouterClient | None = None
        mal_client: MalClient | None = None

        if openrouter_key:
            openrouter = OpenRouterClient(openrouter_key)
        if mal_client_id:
            mal_client = MalClient(mal_client_id)

        try:
            processor = SeasonProcessor(bgmtv, openrouter, mal_client)

            if command == "run":
                processor.process(year, season)
            elif command == "release":
                processor.generate_release_from_state(year, season)
            elif command == "complete":
                processor.complete_state(year, season)
        finally:
            if openrouter:
                openrouter.close()
            if mal_client:
                mal_client.close()


if __name__ == "__main__":
    main()
