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
| `BGM_TOKEN` | Bangumi.tv API token | 可选，提高限速 |
| `OPENROUTER_API_KEY` | LLM 匹配 ([OpenRouter](https://openrouter.ai/)) | run 时需要 |
| `DEEPSEEK_API_KEY` | LLM 匹配（DeepSeek，优先于 OpenRouter） | run 时需要 |
| `GITHUB_TOKEN` | 发布 GitHub Release | publish 时需要 |

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
4. Export Release 生成 `release/{year}-{season}.json`

## 命令行（可选）

也可以跳过 Web UI，直接用 CLI：

```bash
# 获取 MAL 原始数据
PYTHONPATH=src uv run python -m services.mal fetch 2026 winter

# 处理季度新番匹配
PYTHONPATH=src uv run python -m core run 2026 winter

# 人工填入 bgm_id 后补全名称 + 重新生成 release
PYTHONPATH=src uv run python -m core complete 2026 winter

# 从数据库重新生成 release（不调用 API）
PYTHONPATH=src uv run python -m core release 2026 winter

# 批量处理所有历史季度
PYTHONPATH=src uv run python src/main.py
```

## Override 补番

MAL 有时会把某季番标到错误季度，可以通过 Web UI 的 Override Manager 或直接操作数据库添加补丁：

- **add**：强制将某 MAL ID 加入本季，并指定 bgm_id
- **skip**：强制将某 MAL ID 排除

## 发布

```bash
uv run python scripts/publish_release.py
```

合并所有 `release/*.json` 并发布到 GitHub Release。

## 目录结构

```
season.db              主数据库（seasons / items / overrides）
release/               最终发布文件
src/
  api/                 FastAPI 后端
    routers/           seasons / items / overrides / run / export / bgm
    migrations/        SQL 初始化脚本
  core/                匹配主逻辑 + CLI
  services/mal/        MAL API 客户端
  services/bgmtv/      Bangumi.tv API 客户端
  services/openrouter/  OpenRouter / DeepSeek LLM 客户端
web/                   Astro + React 前端
scripts/               辅助脚本（publish、migrate）
```

## 开发

```bash
uv run mypy src/     # 类型检查
uv run ruff check    # lint
uv run ruff format   # 格式化
```
