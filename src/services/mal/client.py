from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

BASE_URL = "https://api.myanimelist.net/v2"

FIELDS = (
    "id,title,alternative_titles,start_date,end_date,synopsis,"
    "media_type,status,num_episodes,start_season,broadcast,source,studios,rating"
)

SEASON_VALUES = ("winter", "spring", "summer", "fall")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
RELEASE_DIR = PROJECT_ROOT / "data" / "mal"

MAX_RETRIES = 3
RETRY_DELAY = 5.0
REQUEST_INTERVAL = 0.5


class MalClient:
    def __init__(self, client_id: str) -> None:
        self.client = httpx.Client(
            headers={"X-MAL-CLIENT-ID": client_id},
            timeout=30.0,
            follow_redirects=False,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> MalClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _get(self, url: str, params: dict[str, str | int]) -> httpx.Response:
        """带重试的 GET 请求。"""
        for attempt in range(1, MAX_RETRIES + 1):
            resp = self.client.get(url, params=params)
            if resp.status_code in (307, 429, 500, 502, 503):
                delay = RETRY_DELAY * attempt
                logger.warning(
                    "请求失败 ({}), 第 {}/{} 次重试, 等待 {}s...",
                    resp.status_code,
                    attempt,
                    MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp  # unreachable, but keeps mypy happy

    def get_anime(self, anime_id: int) -> dict[str, Any]:
        """获取单条动漫数据。"""
        url = f"{BASE_URL}/anime/{anime_id}"
        params: dict[str, str | int] = {"fields": FIELDS}
        resp = self._get(url, params)
        result: dict[str, Any] = resp.json()
        return result

    def get_seasonal_anime(
        self,
        year: int,
        season: str,
        *,
        limit: int = 500,
        offset: int = 0,
        nsfw: bool = True,
    ) -> dict[str, Any]:
        """获取指定季度的新番列表（单页）。"""
        url = f"{BASE_URL}/anime/season/{year}/{season}"
        params: dict[str, str | int] = {
            "fields": FIELDS,
            "limit": min(limit, 500),
            "offset": offset,
        }
        if nsfw:
            params["nsfw"] = "true"

        resp = self._get(url, params)
        result: dict[str, Any] = resp.json()
        return result

    def get_all_seasonal_anime(
        self,
        year: int,
        season: str,
        *,
        nsfw: bool = True,
    ) -> list[dict[str, Any]]:
        """获取指定季度的所有新番（自动分页）。"""
        all_anime: list[dict[str, Any]] = []
        offset = 0
        limit = 500

        while True:
            resp = self.get_seasonal_anime(
                year, season, limit=limit, offset=offset, nsfw=nsfw
            )
            data: list[dict[str, Any]] = resp.get("data", [])
            count = len(data)
            for entry in data:
                all_anime.append(entry["node"])

            paging = resp.get("paging", {})
            if not paging.get("next") or count < limit:
                break

            offset += limit

        return all_anime


def _save(year: int, season: str, items: list[dict[str, Any]]) -> Path:
    """将获取到的新番数据保存到 data/mal/{year}-{season}.json。"""
    tz = timezone(timedelta(hours=8))
    output = {
        "season": f"{year}-{season}",
        "update_time": datetime.now(tz).isoformat(timespec="seconds"),
        "items": sorted(items, key=lambda x: x["id"]),
    }

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RELEASE_DIR / f"{year}-{season}.json"
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_path


def fetch_and_save(year: int, season: str, client_id: str) -> Path:
    """获取单个季度新番并保存。"""
    if season not in SEASON_VALUES:
        raise ValueError(f"无效的季度: {season}，可选值: {SEASON_VALUES}")

    with MalClient(client_id) as client:
        logger.info("正在获取 {}-{} 季度新番...", year, season)
        items = client.get_all_seasonal_anime(year, season)
        logger.info("共获取 {} 条记录", len(items))

    out_path = _save(year, season, items)
    logger.info("已保存到 {}", out_path)
    return out_path


def sort_all() -> int:
    """对 release/mal/ 下所有 JSON 文件的 items 按 id 排序。"""
    files = sorted(RELEASE_DIR.glob("*.json"))
    count = 0
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        items = data.get("items", [])
        sorted_items = sorted(items, key=lambda x: x["id"])
        if items != sorted_items:
            data["items"] = sorted_items
            f.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            count += 1
            logger.info("已排序: {}", f.name)
    logger.info("完成: 共处理 {} 个文件, 其中 {} 个需要排序", len(files), count)
    return count


def fetch_range(
    start_year: int,
    start_season: str,
    end_year: int,
    end_season: str,
    client_id: str,
) -> list[Path]:
    """批量获取从 start 到 end（含）的所有季度新番并保存。跳过已有文件。"""
    seasons = list(SEASON_VALUES)
    si = seasons.index(start_season)
    ei = seasons.index(end_season)

    targets: list[tuple[int, str]] = []
    for y in range(start_year, end_year + 1):
        for i, s in enumerate(seasons):
            if (y == start_year and i < si) or (y == end_year and i > ei):
                continue
            targets.append((y, s))

    logger.info("共 {} 个季度待获取", len(targets))
    paths: list[Path] = []
    skipped = 0

    with MalClient(client_id) as client:
        for idx, (year, season) in enumerate(targets, 1):
            out_path = RELEASE_DIR / f"{year}-{season}.json"
            if out_path.exists():
                skipped += 1
                continue

            logger.info("[{}/{}] 正在获取 {}-{}...", idx, len(targets), year, season)
            items = client.get_all_seasonal_anime(year, season)
            logger.info("共获取 {} 条记录", len(items))
            paths.append(_save(year, season, items))
            time.sleep(REQUEST_INTERVAL)

    logger.info("完成: 新获取 {} 个, 跳过已有 {} 个", len(paths), skipped)
    return paths
