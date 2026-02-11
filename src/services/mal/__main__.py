from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from .client import fetch_and_save, fetch_range, sort_all

SEASONS = ["winter", "spring", "summer", "fall"]


def _get_client_id() -> str:
    client_id = os.environ.get("MAL_CLIENT_ID", "")
    if not client_id:
        print("错误: 未设置 MAL_CLIENT_ID 环境变量", file=sys.stderr)
        sys.exit(1)
    return client_id


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="MAL 季度新番数据获取")
    sub = parser.add_subparsers(dest="command")

    fetch_parser = sub.add_parser("fetch", help="获取单个季度")
    fetch_parser.add_argument("year", type=int, help="年份，如 2026")
    fetch_parser.add_argument("season", choices=SEASONS, help="季度")

    range_parser = sub.add_parser("range", help="批量获取多个季度")
    range_parser.add_argument("start_year", type=int)
    range_parser.add_argument("start_season", choices=SEASONS)
    range_parser.add_argument("end_year", type=int)
    range_parser.add_argument("end_season", choices=SEASONS)

    sub.add_parser("sort", help="对已有 JSON 文件按 id 排序")

    args = parser.parse_args()

    if args.command == "fetch":
        path = fetch_and_save(args.year, args.season, _get_client_id())
        print(f"已保存到 {path}")
    elif args.command == "range":
        paths = fetch_range(
            args.start_year,
            args.start_season,
            args.end_year,
            args.end_season,
            _get_client_id(),
        )
        print(f"共保存 {len(paths)} 个文件")
    elif args.command == "sort":
        sort_all()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
