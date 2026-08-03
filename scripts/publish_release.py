"""从 season.db 读取全部 included 条目，合并为一个文件并发布到 GitHub Release。

用法:
  uv run python scripts/publish_release.py [--tag TAG] [--dry-run]

默认 tag 为当前日期 (如 v2026-02-26)。
--dry-run 只生成合并文件，不创建 GitHub Release。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "season.db"

# 下游服务接受的 media_type 枚举，必须与其保持一致。
# MAL 偶尔返回 `unknown` 等不在此集合内的值，会导致下游整份 JSON 解析失败，需在发布前剔除。
VALID_MEDIA_TYPES = frozenset({"tv", "movie", "ova", "ona", "tv_special", "special", "music", "pv", "cm"})


def merge_releases(db_path: Path) -> dict:
    """读取 DB 中全部 included 条目，合并为 { season_id: [items] }。

    每个 item 只保留 bgm_id / media_type / rating。
    media_type 不在 VALID_MEDIA_TYPES 内、或缺 bgm_id 的条目会被剔除并打印警告，避免下游解析失败。
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        # 先把全部季度铺成空列表，保证没有 included 条目的季度也出现在产物里
        merged: dict = {row["id"]: [] for row in conn.execute("SELECT id FROM seasons ORDER BY id")}

        rows = conn.execute(
            """
            SELECT season_id, mal_id, mal_title, bgm_id, mal_media_type, mal_rating
            FROM items
            WHERE status = 'included'
            ORDER BY season_id, mal_id
            """
        ).fetchall()
    finally:
        conn.close()

    skipped = 0
    for row in rows:
        season = row["season_id"]
        media_type = row["mal_media_type"]
        if media_type not in VALID_MEDIA_TYPES or row["bgm_id"] is None:
            skipped += 1
            reason = f"media_type={media_type!r}" if media_type not in VALID_MEDIA_TYPES else "缺少 bgm_id"
            print(
                f"[warn] 跳过非法 {reason} 条目: season={season} mal_id={row['mal_id']} 「{row['mal_title']}」",
                file=sys.stderr,
            )
            continue
        merged.setdefault(season, []).append(
            {
                "bgm_id": row["bgm_id"],
                "media_type": media_type,
                "rating": row["mal_rating"] or "",
            }
        )
    if skipped:
        print(f"共跳过 {skipped} 条非法 media_type 条目", file=sys.stderr)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="合并 data 并发布到 GitHub")
    parser.add_argument(
        "--tag",
        default=f"v{datetime.now(UTC).strftime('%Y-%m-%d')}",
        help="GitHub Release tag (默认: v{当前日期})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只生成合并文件到 stdout，不发布",
    )
    args = parser.parse_args()

    if not DB_PATH.is_file():
        print(f"Error: 数据库不存在: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    merged = merge_releases(DB_PATH)
    print(f"合并了 {len(merged)} 个季度", file=sys.stderr)

    if args.dry_run:
        print(json.dumps(merged, ensure_ascii=False))
        return

    # 写入固定文件名，确保 asset name 正确
    tmp_dir = Path(tempfile.mkdtemp())
    asset_path = tmp_dir / "season-data.json"
    asset_path.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")

    tag = args.tag

    # 删除已有的同名 release（支持同一天重复发布）
    subprocess.run(
        ["gh", "release", "delete", tag, "--yes", "--cleanup-tag"],
        capture_output=True,
    )

    print(f"创建 GitHub Release: {tag}", file=sys.stderr)
    try:
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                tag,
                str(asset_path),
                f"--title={tag}",
                f"--notes=季度数据合并发布 ({len(merged)} seasons)",
            ],
            check=True,
        )
    except FileNotFoundError:
        print("Error: 未找到 gh 命令，请安装 GitHub CLI", file=sys.stderr)
        sys.exit(1)
    finally:
        asset_path.unlink(missing_ok=True)
        tmp_dir.rmdir()


if __name__ == "__main__":
    main()
