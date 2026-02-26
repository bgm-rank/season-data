"""将 release/ 下所有季度 JSON 合并为一个文件并发布到 GitHub Release。

用法:
  uv run python scripts/publish_release.py [--tag TAG] [--dry-run]

默认 tag 为当前日期 (如 v2026-02-26)。
--dry-run 只生成合并文件，不创建 GitHub Release。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

RELEASE_DIR = Path(__file__).resolve().parent.parent / "release"


def _slim_item(item: dict) -> dict:
    """只保留 bgm_id, media_type, rating。"""
    mal = item.get("mal", {})
    return {
        "bgm_id": item["bgm_id"],
        "media_type": mal.get("media_type", ""),
        "rating": mal.get("rating", ""),
    }


def merge_releases(release_dir: Path) -> dict:
    """读取所有季度 release JSON，合并为 { season: [items] }。"""
    merged: dict = {}
    for f in sorted(release_dir.glob("*.json")):
        data = json.loads(f.read_text("utf-8"))
        season = data.get("season", f.stem)
        merged[season] = [_slim_item(it) for it in data.get("items", [])]
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="合并 release 并发布到 GitHub")
    parser.add_argument(
        "--tag",
        default=f"v{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        help="GitHub Release tag (默认: v{当前日期})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只生成合并文件到 stdout，不发布",
    )
    args = parser.parse_args()

    if not RELEASE_DIR.is_dir():
        print(f"Error: release 目录不存在: {RELEASE_DIR}", file=sys.stderr)
        sys.exit(1)

    merged = merge_releases(RELEASE_DIR)
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
