# dev.md — 数据库重构评估：拆分 `items` 为 mal / bgmtv / 季度 / 关联四表

> 2026-08-03。针对「重新设计数据库作为 `todo.md` 的前置任务」这一想法的评估。
> **前提（2026-08-03 修订）**：抛弃 `data/` 目录、放弃跨机器同步、只在一台电脑上工作。
> 本文档已按该前提改写；被这个前提消灭的内容见 §5。
> 结论先行：**方向正确，但理由不是你可能以为的那个，且不该作为全部 P0 的前置任务。**

---

## 0. 结论摘要

| 问题 | 回答 |
|---|---|
| 该不该拆？ | 该拆。 |
| 拆表的真正收益是什么？ | **不是省空间，是隔离写入边界** —— 让"可重建的缓存"和"不可重建的人工决策"物理分离。 |
| 是 `todo.md` 的前置任务吗？ | 只是 P1 中 **2-3 / 4-2 / 4-3 / 5-1** 的前置任务。P0 里 1-1、5-3、5-2 都不依赖它，合计一天，应当先做。 |
| 抛弃 `data/` 的影响 | 成本从 3 天降到 **1.5 天**，todo 4-1 整项消失，三个脚本可删。**但备份归零，必须换一套备份手段** —— 见 §5。 |
| 最大风险 | 无测试套件 + `season.db` 成为 20596 条数据的**唯一副本**且不在版本控制里。 |
| 安全网 | `publish_release.py --dry-run` 前后输出必须**逐字节一致** + 重构前 `VACUUM INTO` 备份。 |

---

## 1. 现状的结构性缺陷

`items` 一张宽表里塞了三类**生命周期完全不同**的数据：

| 类别 | 列 | 来源 | 刷新时机 | 丢了会怎样 |
|---|---|---|---|---|
| MAL 事实 | `mal_title` / `mal_title_ja` / `mal_media_type` / `mal_rating` | MAL API | 每次 fetch | 重拉即可 |
| BGM 事实 | `bgm_name` / `bgm_name_cn` / `bgm_air_date` | BGM API | sync-bgm | 重拉即可 |
| 匹配决策 | `status` / `source` / `confidence` / `bgm_id` / `candidates` / `error` | 规则 / LLM / **人工** | run / 人工审核 | **不可重建，要重审 2 万条** |

前两类是**可重建的缓存**，第三类是**不可重建的资产**。把它们放在同一行，直接导致了 `todo.md` 里两个 P0：

- **1-1**（fetch 清空全部匹配数据）：`INSERT OR REPLACE` 语义是整行 DELETE+INSERT。刷新缓存的操作物理上碰得到人工资产，只能靠"记得把 15 个列名都写对"来防止灾难 —— 而它已经失败了。
- **4-1**（export/import 丢 `bgm_air_date`）：同一个病因。宽表让快照脚本必须手写一份 15 列的字段清单，加列时三处（export dict / import 列名 / import 占位符）漏一处就静默丢数据 —— 它也已经失败了。

这两个 bug 不是手滑，是**结构在鼓励手滑**。拆表后，`fetch` 的 SQL 里根本不存在 `status` 这个列名，1-1 类事故不再可能发生。

**这是拆表唯一站得住的核心论据。**

> 抛弃 `data/` 后 4-1 作为待办消失（没有 export 就没有丢字段），但它作为病因证据依然有效 —— 同一个结构缺陷制造了两个不同形态的静默数据丢失。
> 同时 **1-1 的严重性反而上升**：`data/` 在的时候，被 fetch 清空的季度还能 `git checkout data/{season}.json` + `import_db.py` 捞回来；单机模式下这条退路没有了，点错一次就是永久损失。**这使 1-1 成为唯一一个必须在抛弃 `data/` 之前修掉的任务。**

---

## 2. 先否掉两个站不住的理由

做重构前先把假收益排掉，免得为了错误的理由付出正确的代价：

**❌ "范式化能省存储"** —— 实测不成立：

```
items 总行数        20596
distinct mal_id     20587   → 跨季重复的 mal_id 只有 9 个，MAL 侧去重省 0.04%
有 bgm_id 的行      11805
distinct bgm_id     11068   → BGM 侧去重省 6%
season.db 10.2 MB / data/ 17 MB
```

`is_new_anime` 只保留 `start_season` 严格等于本季的条目（`src/core/season.py:30`），所以一个 MAL 条目本来就几乎只属于一个季度。**别拿"消除冗余"当理由。**

**❌ "拆表能解决撞车/错配"** —— 也不成立。227 组季内撞车、774 条韩文条目错配，根因是 `todo.md` 2-1（管线顺序）和 2-2（后缀剥离过度 + exact 不校验日期），是**匹配逻辑的 bug**。换 schema 一条都修不掉。拆表只是让这些问题**更容易被查出来**（见 §3.4）。

---

## 3. 拆表能兑现的真实收益

### 3.1 写入边界隔离（对应 1-1，P0）

拆完后各写入方的作用域是互斥的：

| 操作 | 能写的表 |
|---|---|
| `POST /seasons/{id}/fetch` | 仅 `mal_anime` + `season_items` 的新行插入 |
| `sync-bgm` | 仅 `bgm_subject` |
| `run` / 人工审核 | 仅 `season_items` 的决策列 |

fetch 破坏人工决策从"需要正确写 upsert 的 15 个列名"降级为"SQL 里压根没有那个表"。

### 3.2 大字段有地方放（对应 2-3、4-2，P1 的主要阻塞）

`todo.md` 2-3 要给 LLM 喂 MAL 的 `synopsis`/`studios`/`num_episodes`，4-2 要存 BGM 的 `summary`/`platform`/`tags`。在当前宽表里做这件事，`items` 会从 16 列膨胀到 25+ 列，且这些**按 `bgm_id`/`mal_id` 天然唯一**的大字段被绑在 `(season_id, mal_id)` 的粒度上 —— 语义错位（一个 BGM 条目的 summary 不属于某个季度），刷新时也无法只更新缓存部分。

> **诚实说明**：保留 `data/` 时，这一节还有另一半论据 ——「可重建的缓存会跟人工决策捆绑进同一份 git 快照，17MB 膨胀到 50MB+」。**抛弃 `data/` 后这半个理由不成立了**，本节的说服力相应下降。剩下的语义错位理由仍然有效，但如果 §5.3 采纳了「只导决策」的 `decisions.jsonl` 方案，那一半论据会以更弱的形式回来（大字段本来也不会进那个文件）。

### 3.3 增量同步与人工填 ID 的正确性由约束保证（对应 3-2、4-3）

`bgm_subject` 允许只有 `bgm_id` 的骨架行，`fetched_at IS NULL` 表示未填充。于是：

- **4-3 的增量同步**：待刷队列就是 `SELECT bgm_id FROM bgm_subject WHERE fetched_at IS NULL`，天然支持跨季、断点续传，不需要 `only_missing` 参数这种打补丁的设计。
- **3-2 的人工填 ID 无反馈**：`season_items.bgm_id` 走外键指向 `bgm_subject`，写入前必须先落一条 subject 行，顺手就把名称拉回来了。约束逼出正确行为，而不是靠记得在 `items.py` 的 include 分支里补三行代码。

### 3.4 质量检查从"脚本"变成"查询"（对应 5-1，P0 的最高价值项）

`dup_in_season` / `dup_global` / `date_mismatch` 在关联表上都是带索引的一句 SQL，`date_mismatch` 还能直接 JOIN `bgm_subject.air_date` 和 `seasons` 的日期范围，不再依赖每行冗余的 `bgm_air_date`（那列现在只有 3% 覆盖率，正是因为它是冗余副本，谁都能忘了写）。

> 注意：**不要给 `season_items.bgm_id` 加 UNIQUE**。MAL 拆分 / BGM 合并（剧场版、SP、分季）导致 N:1 和 1:N 在现实中都合法，硬约束会挡掉正确数据。撞车只能是**质量视图**，不能是约束。

---

## 4. 表设计

四张表（沿用你的划分），加上不动的 `seasons` 和 `overrides`：

```sql
-- 003_split_tables.sql（新增，不改已有迁移文件）

CREATE TABLE mal_anime (            -- MAL 侧事实，可重建缓存
    mal_id            INTEGER PRIMARY KEY,
    title             TEXT NOT NULL,
    title_ja          TEXT,
    title_en          TEXT,
    media_type        TEXT NOT NULL,
    rating            TEXT NOT NULL,
    start_date        TEXT,
    end_date          TEXT,
    num_episodes      INTEGER,
    source            TEXT,          -- 原作类型 (manga/light_novel/...)
    studios           TEXT,          -- JSON array
    synopsis          TEXT,
    start_season_year INTEGER,
    start_season      TEXT,
    fetched_at        TEXT
);

CREATE TABLE bgm_subject (          -- BGM 侧事实，可重建缓存
    bgm_id     INTEGER PRIMARY KEY,
    type       INTEGER,
    name       TEXT,
    name_cn    TEXT,
    air_date   TEXT,
    platform   TEXT,                -- TV / 剧场版 / OVA，可与 media_type 交叉验证
    summary    TEXT,
    tags       TEXT,                -- JSON array
    nsfw       INTEGER,
    fetched_at TEXT                 -- NULL = 骨架行，待同步（见 §3.3）
);

CREATE TABLE season_items (         -- 关联 + 决策，不可重建资产
    season_id  TEXT    NOT NULL REFERENCES seasons(id),
    mal_id     INTEGER NOT NULL REFERENCES mal_anime(mal_id),
    status     TEXT    NOT NULL CHECK(status IN ('pending','included','excluded')),
    source     TEXT    CHECK(source IN ('rule','exact','llm','human') OR source IS NULL),
    confidence REAL,
    bgm_id     INTEGER REFERENCES bgm_subject(bgm_id),   -- 不加 UNIQUE，见 §3.4
    candidates TEXT,                -- JSON: [{bgm_id, confidence, reason}]，名称一律 JOIN 取
    error      TEXT,
    origin     TEXT NOT NULL DEFAULT 'mal' CHECK(origin IN ('mal','override')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (season_id, mal_id)
);

CREATE INDEX idx_si_season_status ON season_items(season_id, status);
CREATE INDEX idx_si_bgm           ON season_items(bgm_id) WHERE bgm_id IS NOT NULL;
```

关键决策及理由：

1. **关联表 PK 保持 `(season_id, mal_id)`，一个季度条目最多一个 bgm_id。** 与当前语义完全一致，迁移无损。不要顺手做成多对多 —— 下游 release 格式是 `season → [{bgm_id, media_type, rating}]`（`publish_release.py:29-35`），根本消费不了多对多，那是范围蔓延。
2. **`candidates` 保留 JSON，不建第五张表。** 41686 个候选引用分布在 13341 行里，独立成表只在"某 bgm_id 被多少条目当过候选"这一种查询上有优势，不值当。但**要把 `bgm_name`/`air_date` 从 JSON 里删掉**，改为渲染时 JOIN `bgm_subject` —— 现在 JSON 里存的名称是快照，BGM 改名后就是错的。顺手把 2-3 要的 `reason` 加进去。
3. **`origin` 列吸收 overrides 的 `add` 语义**，`overrides` 表保留原样（它是人工输入的意图记录，与派生状态是两回事）。
4. **`bgm_air_date` 不再在关联表里冗余**，直接 JOIN `bgm_subject`。它现在只有 3% 覆盖率，正是因为冗余副本谁都能忘了写；改成单一来源后，`date_mismatch` 质量检查才有可靠的数据基础。

### 前端零改动

API 层用一个 VIEW 或 JOIN 拼回当前 `ItemRead` 的扁平形状：

```sql
CREATE VIEW items_flat AS
SELECT si.mal_id, si.season_id, si.status, si.source, si.confidence, si.bgm_id,
       b.name AS bgm_name, b.name_cn AS bgm_name_cn, b.air_date AS bgm_air_date,
       m.title AS mal_title, m.title_ja AS mal_title_ja,
       m.media_type AS mal_media_type, m.rating AS mal_rating,
       si.error, si.candidates, si.updated_at
FROM season_items si
JOIN mal_anime m USING (mal_id)
LEFT JOIN bgm_subject b ON b.bgm_id = si.bgm_id;
```

`schemas.py` 的 `ItemRead` 和 `web/src/types/api.ts` 都不用动，**重构完全限制在后端存储层**。新字段（synopsis/platform/tags）在后续 P1 里按需加进响应，与本次重构解耦。这是本方案最重要的降风险手段。

---

## 5. 抛弃 `data/`：省了什么，欠了什么

### 5.1 省掉的

`data/` 的消费者只有三个脚本，前端和 API 完全不碰它：

| 文件 | 处置 | 行数 |
|---|---|---|
| `scripts/export_db.py` | 删 | 111 |
| `scripts/import_db.py` | 删 | 119 |
| `scripts/migrate_to_db.py` | 删（一次性历史脚本，早已用完） | 239 |
| `scripts/publish_release.py` | **改**：`merge_releases()` 从读 `data/*.json` 改为读 DB | ~20 行改动 |
| `README.md:68-80`「数据库备份与恢复」 | 重写为 §5.3 的方案 | — |

连带消失的：

- **`todo.md` 4-1 整项**（export/import 丢 `bgm_air_date`）—— 没有 export 就没有字段清单可漏
- 本文档原 §5 的快照格式设计（jsonl 分片、大字段是否入 git、按 `PRAGMA table_info` 动态生成字段列表）
- 原 §6 第 5 步的 **17MB 全量 diff** 和随之而来的 blame 断裂
- 「可重建缓存 vs 不可重建资产，哪些进 git」这个纠结 —— 单机模式下两者都不进 git
- **提交纪律**：不再需要"改完数据记得跑 `export_db.py` 再提交"（`todo.md` §6 最后一条、CLAUDE.md 约定）

重构成本从 **~3 天降到 ~1.5 天**，主要是砍掉了"export/import 重写 + 快照格式"的一天。

### 5.2 `publish_release.py` 改读 DB 是净收益

这不只是被迫的适配。当前发布链路是 `DB → export_db.py → data/*.json → publish_release.py`，中间那一步靠人记得跑 —— **而它已经失效了**（见 §5.4 的实测）。直连 DB 后，发布的一定是当前状态，少一个能静默发布陈旧数据的环节。

改动就是把 `merge_releases()` 换成一句 SQL：

```sql
SELECT si.season_id, si.bgm_id, m.media_type, m.rating
FROM season_items si JOIN mal_anime m USING (mal_id)
WHERE si.status='included' AND si.bgm_id IS NOT NULL
  AND m.media_type IN (...)          -- 原 VALID_MEDIA_TYPES 过滤
ORDER BY si.season_id, si.mal_id
```

`VALID_MEDIA_TYPES` 的剔除逻辑和警告输出照搬，输出结构不变。

### 5.3 欠下的：备份归零，必须补

**这是抛弃 `data/` 唯一真正的代价，不能含糊过去。**

`season.db` 是 gitignored 的单个 10.2MB 文件。抛弃 `data/` 后，20596 条条目 —— 其中 **182 条纯人工决策**（human included 48 + human excluded 134）和全部审核成果 —— 在全世界只有这一个副本，不在版本控制里，没有任何历史。一次误删、一次 WSL 崩坏、一次迁移脚本写错，全没。

这跟本文档 §1 的核心论证直接冲突：整个重构的理由是「保护不可重建的资产」，而抛弃 `data/` 等于拆掉这个资产的最后一道防线。**所以不是不能抛弃 `data/`，是不能在没有替代品的情况下抛弃。**

替代方案（推荐前两条一起做）：

1. **重构前后各做一次整库快照** —— 一秒钟的事，直接放进操作步骤：
   ```bash
   uv run python -c "import sqlite3;sqlite3.connect('season.db').execute(\"VACUUM INTO 'backups/season-20260803.db'\")"
   ```
   `backups/` 加进 `.gitignore`。这是重构期间的救命绳。

2. **保留一份极简的决策导出，进 git** —— 这才是对 §1 原则的正确执行：只备份不可重建的部分，可重建的缓存（MAL/BGM 事实）一概不存。
   ```
   data/decisions.jsonl    # season_id, mal_id, status, source, bgm_id, confidence
   ```
   20596 行、约 1MB，按 `(season_id, mal_id)` 排序 → git diff 是行级的，改 10 条就只有 10 行变化。对比现在 17MB、每次 export 全量重写的 `data/`，**体积降到 6%，diff 质量还更高**。
   恢复时 MAL 事实重拉、BGM 事实重拉（`fetched_at IS NULL` 队列本来就支持），只有决策不可重建 —— 而它在 git 里。

   > 这条严格来说超出了「抛弃 data/」的字面要求。但它的成本是一个 ~30 行的脚本，换来的是人工审核成果有版本历史。如果嫌麻烦，**至少要做第 1 条**。

3. 只做第 1 条 + 定期手动备份：可以接受，但要明确这是在拿"重构 3 天 + 未来所有审核工时"赌不出意外。

### 5.4 抛弃前必须确认漂移方向（已实测）

`data/` 和 DB 现在**已经不一致**了：

```
DB 行数 20596 / data 行数 20596，仅 DB 有 0，仅 data 有 0，值不同 14
  ('2024-fall', 60901)  db=(excluded, human, None)    data=(included, exact, 629655)
  ('2024-fall', 58531)  db=(excluded, human, 426156)  data=(included, llm,   426156)
  ... 14 条全部在 2024-fall，全部是 db=excluded/human ← data=included/llm|exact
included 数量：db 11782 / data 11796，对称差 14
```

**方向是安全的**：全部 14 条都是 DB 领先（人工把 LLM 的错配排除掉了），`data/` 落后一次未导出的审核。直接抛弃 `data/` 不会丢任何东西。

但这 14 条同时说明：**"改完数据记得跑 export_db"这条纪律已经失效过一次**。这既是抛弃 `data/` 的论据（少一个必须记住的手工步骤），也是 §5.3 的论据（备份手段必须是自动的，不能依赖记性）。

复核脚本：

```bash
uv run python - <<'EOF'
import json, sqlite3
from pathlib import Path
c = sqlite3.connect('season.db'); c.row_factory = sqlite3.Row
db = {(r['season_id'], r['mal_id']): (r['status'], r['source'], r['bgm_id'])
      for r in c.execute("SELECT season_id, mal_id, status, source, bgm_id FROM items")}
fs = {}
for f in sorted(Path('data').glob('*.json')):
    for it in json.loads(f.read_text('utf-8')).get('items', []):
        fs[(it['season_id'], it['mal_id'])] = (it['status'], it['source'], it['bgm_id'])
diff = [k for k in db.keys() & fs.keys() if db[k] != fs[k]]
print("仅DB:", len(db.keys()-fs.keys()), "仅data:", len(fs.keys()-db.keys()), "值不同:", len(diff))
for k in diff[:20]: print(" ", k, "db=", db[k], "data=", fs[k])
EOF
```

---

## 6. 迁移路线

### 第 0 步：抛弃 `data/` 之前（必须按这个顺序）

1. **修 `todo.md` 1-1**（fetch 改 upsert，30min）。见 §1 的注记 —— `data/` 一撤，这个 bug 从"可恢复"变成"永久损失"。
2. `uv run python scripts/export_db.py` 跑最后一次，把 §5.4 那 14 条漂移落盘并提交，`data/` 与 DB 归零。
3. 用**当前代码**生成发布基线：`uv run python scripts/publish_release.py --dry-run > /tmp/before.json`。
4. 把 `publish_release.py` 改成读 DB（§5.2），在**旧 schema 上**先跑一次 `--dry-run` 与 `/tmp/before.json` 对拍 —— 这一步同时验证了"改读 DB"和"data/ 与 DB 已一致"两件事。
5. 确认一致后，删 `data/`、删三个脚本、改 README、建立 §5.3 的备份手段。
6. `VACUUM INTO 'backups/season-before-split.db'`。

至此 `/tmp/before.json` 成为整个重构唯一且可信的回归基线。

### 第 1 步：结构就位，代码未切

7. `src/api/migrations/003_split_tables.sql`：建四张新表 + `items_flat` 视图。**不删 `items`**。
8. `scripts/migrate_split.py`：从 `items` 回填
   - `mal_anime`：20587 行，新字段（synopsis/studios/...）留空，等一次 MAL 重拉补齐
   - `bgm_subject`：11068 行，从现有 `bgm_name`/`bgm_name_cn`/`bgm_air_date` 回填，**`fetched_at` 一律置 NULL**（等于自动排入 4-3 的待刷队列，顺手补齐那 97% 缺失的 air_date）
   - `season_items`：20596 行，决策列直接搬

### 第 2 步：代码切换

9. `processor.py`（全部 SQL，~200 行）、`routers/{items,seasons,run,overrides}.py` 切到新表；读路径优先走 `items_flat` 视图，写路径按 §3.1 的边界拆开。
10. `publish_release.py` 的 SQL 换成 §5.2 的新表版本，再次与 `/tmp/before.json` 对拍。
11. `004_drop_items.sql`：确认稳定后再删旧表。在此之前 `items` 一直是随时可回滚的完整备份 —— **单机模式下这是主要的回滚手段，别急着删**。

### 验收标准

```bash
# 1. 下游产物不变（最硬的回归验证，全程唯一的安全网）
uv run python scripts/publish_release.py --dry-run > /tmp/after.json
diff /tmp/before.json /tmp/after.json    # 必须为空

# 2. 状态分布不变
SELECT status, source, COUNT(*) FROM season_items GROUP BY 1,2;   # 与 todo.md §现状体检 一致（注意 included 应为 11782，非 11796）

# 3. 行数守恒
20596 season_items / 20587 mal_anime / 11068 bgm_subject

# 4. 视图形状不变：前端不改一行代码，UI 全功能可用
```

> 原方案的第 4 条验收「export → 清空 → import → 再 export，git diff 为空」随 `data/` 一起消失。
> 单机模式下**少了一层往返校验**，所以第 1 条对拍的重要性上升 —— 它现在是唯一的端到端验证。

### 成本

| 项 | 估计 |
|---|---|
| 第 0 步（1-1 + publish 改读 DB + 清理） | 1.5h |
| 迁移 SQL + 回填脚本 | 半天 |
| 后端代码切换（~700 行 Python 涉及） | 1 天 |
| 对拍验证 | 2h |
| **合计** | **约 1.5 天**（保留 `data/` 时是 3 天） |

前端 0（靠 §4 的视图）。

---

## 7. 风险

1. **无测试套件**（CLAUDE.md 明确写了）**且没有 `data/` 兜底**。唯一安全网是 §6 的对拍 + `backups/` 里的 `VACUUM INTO` 副本。**动手前先把 `before.json`、状态分布、整库备份三样都存下来** —— 这三样在单机模式下不是可选项。
2. **回滚路径只剩本地**：保留 `items` 旧表到最后（第 11 步），它是唯一能在不重跑 API 的前提下恢复决策的东西。
3. **重构期间不要审核数据**，否则对拍基线会漂移 —— §5.4 那 14 条就是"边审核边忘了同步"的产物。
4. **`bgm_subject` 骨架行的 FK 时序**：人工填 bgm_id 时若 BGM API 不可用，必须允许先插骨架行（`fetched_at=NULL`）再写关联，不能让外键把人工输入卡死。实现时注意 `get_connection` 里 `PRAGMA foreign_keys=ON` 是开着的。
5. **单个共享 `sqlite3.Connection` 跨线程**（`todo.md` §6）在重构后依然存在，别指望顺手解决。

---

## 8. 与 `todo.md` 的执行顺序

**不要把重构放在最前面。** 建议顺序：

```
阶段 A（一天，不依赖重构）
  1-1  fetch upsert                30min   ← 必须在抛弃 data/ 之前做，见 §1 注记
  5-3  getItems limit              10min
  5-2  ItemList 乐观更新 + 行内操作  半天   ← 纯前端，与重构完全正交
  2-1  语言护栏（韩文直接 excluded）  1h    ← 纯 processor 逻辑，止住 292 条错配继续扩散
  2-2  收窄后缀剥离 + exact 日期校验  半天  ← 同上，止住撞车主因
  ——  4-1 已随 data/ 一起消失，不用做

阶段 A′（1.5h）§6 第 0 步：清理 data/、publish 改读 DB、建立备份

阶段 B（1.5 天）
  本文档的重构

阶段 C（重构解锁的部分）
  4-3  BGM 增量同步 → 补齐 97% 缺失的 air_date（回填时 fetched_at=NULL 已经排好队）
  5-1  质量检查 API + UI（此时 date_mismatch 才真的可用）
  4-2  BGM 原始数据（已在 bgm_subject 里，只剩填充）
  2-3  增强 LLM prompt（mal_anime 的 synopsis/studios + bgm_subject 的 platform/tags 都已就位）
  §7   一次性清理 700~1000 条问题 included
```

阶段 A 里 1-1 的代码会在阶段 B 被重写，浪费 30 分钟 —— 相比"重构期间又被点一次 fetch 清空一个季度、且没有 `data/` 可以捞回来"，这个保险非常便宜。

**判据**：如果只想解决滚动位置丢失、看不全条目这类手感问题，**不需要重构**，阶段 A 就够了。重构的必要性完全来自阶段 C —— 想认真提升匹配质量（喂更多数据给 LLM、系统性的质量检查），当前 schema 是硬阻塞。
