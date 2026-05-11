from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from loguru import logger

from core.processor import SeasonProcessor
from core.season import SEASON_VALUES
from services.bgmtv import BgmtvClient
from services.mal import MalClient
from services.openrouter import OpenRouterClient

START_YEAR = 2000
END_YEAR = 2025


def main() -> None:
    load_dotenv()

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

            total = (END_YEAR - START_YEAR + 1) * len(SEASON_VALUES)
            current = 0
            failed: list[str] = []

            for year in range(START_YEAR, END_YEAR + 1):
                for season in SEASON_VALUES:
                    current += 1
                    season_key = f"{year}-{season}"
                    logger.info("[{}/{}] 开始处理 {} ...", current, total, season_key)
                    try:
                        processor.process(year, season)
                    except FileNotFoundError:
                        logger.warning(
                            "[{}/{}] {} MAL 数据不存在，跳过",
                            current,
                            total,
                            season_key,
                        )
                        continue
                    except Exception:
                        logger.exception("[{}/{}] {} 处理失败", current, total, season_key)
                        failed.append(season_key)

            logger.info("全部完成: 共 {} 个季度, 失败 {}", total, len(failed))
            if failed:
                logger.warning("失败列表: {}", failed)
                sys.exit(1)

        finally:
            if openrouter:
                openrouter.close()
            if mal_client:
                mal_client.close()


if __name__ == "__main__":
    main()
