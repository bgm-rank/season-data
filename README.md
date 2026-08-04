# season-data-py

从 [MAL](https://myanimelist.net/) 获取每季新番列表，自动匹配 [Bangumi.tv](https://bgm.tv/) 对应条目 ID。

匹配策略：媒体类型过滤 → 日文标题精确匹配 → LLM 验证 → Web UI 人工审查。

## Setup

```bash
uv sync
cp .env.example .env  # 填入 API keys
cd web && pnpm install
```

`.env` 配置：

| 变量 | 用途 | 必需 |
| --- | --- | --- |
| `MAL_CLIENT_ID` | MAL API ([申请](https://myanimelist.net/apiconfig)) | fetch 时需要 |
| `BGM_TOKEN` | Bangumi.tv API token | nsfw 条目需要 |
| `OPENROUTER_API_KEY` | LLM 匹配 ([OpenRouter](https://openrouter.ai/)) | run 时需要 |
| `DEEPSEEK_API_KEY` | LLM 匹配（DeepSeek，优先于 OpenRouter） | run 时需要 |
| `LLM_PROMPT_MODE` | 匹配 prompt 丰富度：`low`（默认）/ `high` | 否 |
| `GITHUB_TOKEN` | 发布 GitHub Release | publish 时需要 |

`LLM_PROMPT_MODE=high` 会把 MAL 的首播日期 / 集数 / 原作 / 制作公司 / 简介，
以及 BGM 的 platform / tags / 更长简介一并喂给模型，并要求模型给出判定理由（显示在审查界面的候选卡上）。
输入 token 约为 `low` 的 2.5~3 倍，日常 run 用默认的 `low`，大批量重跑或清理问题数据时再开 `high`。

## 启动

```bash
# 后端 API (port 8000)
PYTHONPATH=src uv run uvicorn api.main:app --reload

# 前端 (port 4321)
cd web && pnpm dev
```

打开 http://localhost:4321 进行季度管理和人工审查。

## 工作流

1. 在 Web UI 创建季度 → Fetch MAL 数据（写入 `season.db`）
2. 点击 Run 触发自动匹配（规则过滤 → 精确匹配 → LLM）
3. 在 Review Queue 审查 `pending` 条目，填入 `bgm_id` 或标记排除
4. 跑 `scripts/export_decisions.py` 把决策快照落进 git

## 命令行（可选）

也可以跳过 Web UI，直接用 CLI：

```bash
# 获取 MAL 原始数据
PYTHONPATH=src uv run python -m services.mal fetch 2026 winter

# 处理季度新番匹配（--retry 重跑已被 LLM 处理过的 pending 条目）
PYTHONPATH=src uv run python -m core run [--retry] 2026 winter

# 批量处理所有历史季度
PYTHONPATH=src uv run python src/main.py
```

人工填入 `bgm_id` 后无需单独的补全命令：再次 `run` 时会自动拉取 BGM 名称并标记为 `human`。

## Override 补番

MAL 有时会把某季番标到错误季度，可以通过 Web UI 的 Override Manager 或直接操作数据库添加补丁：

- **add**：强制将某 MAL ID 加入本季，并指定 bgm_id
- **skip**：强制将某 MAL ID 排除

## 数据库备份与恢复

`season.db`（gitignored）是唯一权威数据源。备份只针对**不可重建**的部分——MAL 和 BGM
的事实随时能重拉，人工审核成果不能。

```bash
# 决策快照（改动数据后运行，产物纳入 git）
uv run python scripts/export_decisions.py

# 整库快照（做破坏性操作前运行，backups/ 不进 git）
uv run python -c "import sqlite3;sqlite3.connect('season.db').execute(\"VACUUM INTO 'backups/season-$(date +%Y%m%d).db'\")"
```

`export_decisions.py` 产出两个文件：

- `data/decisions.jsonl` —— 每行一条决策（`season_id` / `mal_id` / `status` / `source` /
  `bgm_id` / `confidence` / `origin`），按 `(season_id, mal_id)` 排序，所以 git diff 是行级的：
  改 10 条就只有 10 行变化。
- `data/meta.json` —— `seasons` 与 `overrides` 两张小表。

恢复路径：重建空库 → 导入这两个文件 → `fetch` 重拉 MAL 事实 → `sync-bgm` 重拉 BGM 事实
（`bgm_subject.fetched_at IS NULL` 天然就是待刷队列）。

## 发布

```bash
uv run python scripts/publish_release.py
```

直接从 `season.db` 读出全部 included 条目，只取 `bgm_id` / `media_type` / `rating`
发布到 GitHub Release。

## 目录结构

```
season.db              主数据库（gitignored，唯一权威数据源）
                       seasons / mal_anime / bgm_subject / season_items / overrides
backups/               整库快照（gitignored）
data/                  决策快照（git 管理）decisions.jsonl + meta.json
src/
  api/                 FastAPI 后端
    routers/           seasons / items / overrides / run / bgm
    migrations/        SQL 迁移（append-only，按文件名顺序执行）
    repo.py            跨表写入 helper（mal_anime / bgm_subject 的 upsert）
  core/                匹配主逻辑 + CLI
  services/mal/        MAL API 客户端
  services/bgmtv/      Bangumi.tv API 客户端
  services/openrouter/  OpenRouter / DeepSeek LLM 客户端
web/                   Astro + React 前端
scripts/               辅助脚本（publish_release、export_decisions）
```

## 开发

```bash
uv run mypy src/     # 类型检查
uv run ruff check    # lint
uv run ruff format   # 格式化
```
