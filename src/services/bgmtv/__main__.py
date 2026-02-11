from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from .client import BgmtvClient


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Bangumi.tv 条目搜索")
    parser.add_argument("keyword", help="搜索关键词")
    parser.add_argument("--start-date", help="开始日期, 如 2025-12-01")
    parser.add_argument("--end-date", help="结束日期, 如 2026-03-31")
    args = parser.parse_args()

    token = os.environ.get("BGM_TOKEN", "")

    with BgmtvClient(token) as client:
        if args.start_date and args.end_date:
            subjects = client.search_anime_by_keyword(
                args.keyword, args.start_date, args.end_date
            )
        else:
            subjects = client.search_anime_by_keyword_no_date(args.keyword)

    print(f"共找到 {len(subjects)} 条结果:")
    for s in subjects:
        print(f"  [{s.id}] {s.name} / {s.name_cn or ''}")


if __name__ == "__main__":
    main()
