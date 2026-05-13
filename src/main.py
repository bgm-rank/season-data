from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

from dotenv import load_dotenv
from loguru import logger

from api.db import get_connection, init_db
from core.processor import SeasonProcessor
from core.season import SEASON_VALUES
from services.bgmtv import BgmtvClient
from services.mal.client import MalClient
from services.openrouter import DEEPSEEK_BASE_URL, DEFAULT_DEEPSEEK_MODEL, DEFAULT_MODEL, OpenRouterClient

START_YEAR = 2000
END_YEAR = 2025


def main() -> None:
    load_dotenv()

    bgm_token = os.getenv("BGM_TOKEN", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    mal_client_id = os.getenv("MAL_CLIENT_ID", "")

    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    init_db(root / "season.db")
    conn = get_connection(root / "season.db")

    mal: MalClient | None = MalClient(mal_client_id) if mal_client_id else None

    with BgmtvClient(bgm_token) as bgmtv:
        openrouter: OpenRouterClient | None = None
        if deepseek_key:
            model = os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
            openrouter = OpenRouterClient(deepseek_key, model=model, base_url=DEEPSEEK_BASE_URL)
        elif openrouter_key:
            model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
            openrouter = OpenRouterClient(openrouter_key, model=model)

        try:
            total = (END_YEAR - START_YEAR + 1) * len(SEASON_VALUES)
            current = 0
            failed: list[str] = []

            for year in range(START_YEAR, END_YEAR + 1):
                for season in SEASON_VALUES:
                    current += 1
                    season_id = f"{year}-{season}"
                    logger.info("[{}/{}] 开始处理 {} ...", current, total, season_id)

                    if not conn.execute("SELECT 1 FROM seasons WHERE id=?", (season_id,)).fetchone():
                        now = datetime.now(UTC).isoformat()
                        conn.execute(
                            "INSERT OR IGNORE INTO seasons"
                            " (id, year, season, released_at, created_at, updated_at)"
                            " VALUES (?,?,?,NULL,?,?)",
                            (season_id, year, season, now, now),
                        )
                        conn.commit()

                    try:
                        processor = SeasonProcessor(
                            conn=conn,
                            season_id=season_id,
                            bgmtv_client=bgmtv,
                            openrouter_client=openrouter,
                            mal_client=mal,
                        )
                        processor.process()
                    except Exception:
                        logger.exception("[{}/{}] {} 处理失败", current, total, season_id)
                        failed.append(season_id)

            logger.info("全部完成: 共 {} 个季度, 失败 {}", total, len(failed))
            if failed:
                logger.warning("失败列表: {}", failed)
                sys.exit(1)

        finally:
            if openrouter:
                openrouter.close()
            conn.close()


if __name__ == "__main__":
    main()
