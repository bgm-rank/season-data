# season-data-py

从 [MAL](https://myanimelist.net/) 获取每季新番列表，自动匹配 [Bangumi.tv](https://bgm.tv/) 对应条目 ID。

匹配策略：日文标题精确匹配 → LLM 验证 → 保留候选供人工确认。

## Setup

```bash
uv sync
cp .env.example .env  # 填入 API keys
```

`.env` 配置：

| 变量 | 用途 | 必需 |
| --- | --- | --- |
| `MAL_CLIENT_ID` | MAL API ([申请](https://myanimelist.net/apiconfig)) | `run` 时 override add 需要 |
| `BGM_TOKEN` | Bangumi.tv API token | 可选 |
| `OPENROUTER_API_KEY` | LLM 匹配 ([OpenRouter](https://openrouter.ai/)) | `run` 时需要 |

## 命令

```bash
# 获取 MAL 原始数据 (保存到 data/mal/)
PYTHONPATH=src uv run python -m services.mal fetch 2026 winter

# 处理季度新番匹配 (读 data/mal/, 写 state/*/, release/)
PYTHONPATH=src uv run python -m core run 2026 winter

# 人工校对后补全名称 + 重新生成 release
PYTHONPATH=src uv run python -m core complete 2026 winter

# 从 state 重新生成 release (不调用任何 API)
PYTHONPATH=src uv run python -m core release 2026 winter
```

## 工作流

1. fetch MAL 数据
2. run 自动匹配
3. 审查 state/model/ (LLM 决策) 和 state/manual/ (未匹配/错误)
4. 在 state/manual/ 中填入 bgm_id → complete 补全名称
5. release 生成最终文件

## Override 补番

MAL 有时会把某季番标到错误季度，导致 `is_new_anime` 过滤漏番。

创建 `state/override/{year}-{season}.json`：

```json
{
  "add": [63096],
  "skip": [99999]
}
```

- **add**: 按 MAL ID 拉取数据加入本季处理
- **skip**: 强制标记为跳过

下次 `run` 时自动生效。

## 目录结构

```tree
data/mal/              MAL API 原始数据
state/
  override/            手动补番/跳过
  skip/                规则跳过 (special/music/pv 等)
  match/               日文标题精确匹配
  model/               LLM 决策 (可审查)
  manual/              人工处理队列 (unconfirmed/error/human)
release/               最终发布文件
src/
  core/                匹配主逻辑 + CLI
  services/mal/        MAL API 客户端
  services/bgmtv/      Bangumi.tv API 客户端
  services/openrouter/  OpenRouter LLM 客户端
```

## 开发

```bash
uv run mypy src/     # 类型检查
uv run ruff check    # lint
uv run ruff format   # 格式化
```
