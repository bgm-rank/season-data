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
from services.openrouter import OpenRouterClient

START_YEAR = 2000
END_YEAR = 2025


def main() -> None:
    load_dotenv()

    bgm_token = os.getenv("BGM_TOKEN", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")

    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    init_db(root / "season.db")
    conn = get_connection(root / "season.db")

    with BgmtvClient(bgm_token) as bgmtv:
        openrouter: OpenRouterClient | None = None
        if openrouter_key:
            openrouter = OpenRouterClient(openrouter_key)

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
