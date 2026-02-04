#!/usr/bin/env python3
"""
合并 release 目录下的所有 JSON 文件，压缩为只包含必要字段的格式。

输出格式：
{
  "2026": {
    "1": [{"id": 530110, "m": "tv", "r": "gnr"}, ...]
  }
}

字段简写：
  - m: media_type
  - r: rating
  - gnr: general

季度简写：
  - 1: winter, 4: spring, 7: summer, 10: fall

跳过 status 为 unconfirmed 或 error 的条目。

用法：
    python scripts/merge_release.py > release/all-seasons.json
"""

import json
import re
from pathlib import Path

# 季度简写映射
SEASON_MAP = {
    "winter": "1",
    "spring": "4",
    "summer": "7",
    "fall": "10",
}

# rating 简写映射
RATING_MAP = {
    "general": "gnr",
    "kids": "kids",
    "r18": "r18",
}

# 需要跳过的 status
SKIP_STATUS = {"unconfirmed", "error"}


def main():
    release_dir = Path(__file__).parent.parent / "release"
    result = {}

    for json_file in release_dir.glob("**/*-mal.json"):
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)

        # 解析 season: "2026-winter" -> year="2026", season="winter"
        season = data.get("season", "")
        match = re.match(r"(\d{4})-(\w+)", season)
        if not match:
            continue

        year, season_name = match.groups()
        season_key = SEASON_MAP.get(season_name, season_name)

        # 提取必要字段
        items = []
        for item in data.get("items", []):
            # 跳过 unconfirmed 和 error
            if item.get("status") in SKIP_STATUS:
                continue
            if not item.get("bgm_id"):
                continue

            mal = item.get("mal", {})
            media_type = mal.get("media_type")
            rating = mal.get("rating")

            items.append({
                "id": item["bgm_id"],
                "m": media_type,
                "r": RATING_MAP.get(rating, rating),
            })

        if year not in result:
            result[year] = {}
        result[year][season_key] = items

    # 按年份和季度排序
    season_order = {"1": 0, "4": 1, "7": 2, "10": 3}
    sorted_result = {}
    for year in sorted(result.keys()):
        sorted_result[year] = {
            k: result[year][k]
            for k in sorted(result[year].keys(), key=lambda x: season_order.get(x, 99))
        }

    print(json.dumps(sorted_result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
