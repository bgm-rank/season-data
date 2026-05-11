from __future__ import annotations

from typing import Any, cast

SEASON_VALUES = ("winter", "spring", "summer", "fall")


def season_date_range(year: int, season: str) -> tuple[str, str]:
    """返回季度的日期范围 (start_date, end_date)。

    | 季度   | 开始           | 结束           |
    | ------ | -------------- | -------------- |
    | winter | {year-1}-12-01 | {year}-03-31   |
    | spring | {year}-03-01   | {year}-06-30   |
    | summer | {year}-06-01   | {year}-09-30   |
    | fall   | {year}-09-01   | {year}-12-31   |
    """
    if season == "winter":
        return (f"{year - 1}-12-01", f"{year}-03-31")
    elif season == "spring":
        return (f"{year}-03-01", f"{year}-06-30")
    elif season == "summer":
        return (f"{year}-06-01", f"{year}-09-30")
    elif season == "fall":
        return (f"{year}-09-01", f"{year}-12-31")
    else:
        raise ValueError(f"Invalid season: {season}")


def is_new_anime(item: dict[str, Any], year: int, season: str) -> bool:
    """检查 MAL 条目是否为当季新番（非续播）。"""
    start_season = item.get("start_season")
    if start_season is None:
        return False
    return cast(bool, start_season.get("year") == year and start_season.get("season") == season)
