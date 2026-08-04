# Usage

```bash
# 发布到 GitHub Release
uv run python scripts/publish_release.py

# 决策快照（改完数据后跑，产物进 git）
uv run python scripts/export_decisions.py

# 增量拉 BGM 条目详情。待刷队列 = bgm_subject 里 fetched_at IS NULL 的骨架行，
# 拉完就置 fetched_at，随时 Ctrl-C 都能续跑。约 1 秒/条。
PYTHONPATH=src uv run python scripts/sync_bgm.py                     # 全库
PYTHONPATH=src uv run python scripts/sync_bgm.py --season 2023-fall  # 只刷一季
PYTHONPATH=src uv run python scripts/sync_bgm.py --dry-run           # 只看队列多长
```
