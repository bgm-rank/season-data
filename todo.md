# TODO — 季度数据流程改进

> 2026-08-03 全流程 review 产出。写得比较详细，目的是让新会话不用重读代码/查库就能直接动手。
> 结论：手感问题只是表象，真正的问题是**第 4、5 步事实上没跑起来**，且有几个静默 bug 在持续破坏数据 / 制造错误匹配。
> 章节按你的五步流程组织；文末有跨章节的优先级执行顺序。
> 已完成的条目直接删除，不再保留划线记录（病因需要留档的写进 commit message）。条目编号保持稳定，删了不重排。

## 现状体检（2026-08-03，基于 season.db）

```
季度总数 108，其中 95 个季度仍有 pending
included 11796  (exact 7615 / llm 4119 / human 48)
excluded  7054  (rule  6321 / llm  613 / human 134)
pending   1746  (全部 source=NULL；1638 条有候选，108 条无候选，0 条带 error)

bgm_air_date 覆盖率： 347 / 11782 included 条目 = 3%
季内 bgm_id 撞车：    227 组，涉及 466 条 included
全局 bgm_id 重复：    610 个 bgm_id，涉及 1328 条 included
韩文标题条目：        774 条，其中 292 条被 included（llm 160 + exact 132），几乎全错
单季条目数 > 200：    51 个季度（最大 339 条）
```

复核脚本（**本仓库跑 Python 一律用 `uv run python`，不要用 `python3`**）。
注意：旧 `items` 表已冻结，查询一律走 `items_flat` 视图，否则读到的是拆表前的快照。

```bash
uv run python - <<'EOF'
import sqlite3
c = sqlite3.connect('season.db'); c.row_factory = sqlite3.Row
for r in c.execute("SELECT status, source, COUNT(*) n FROM items_flat GROUP BY 1,2 ORDER BY 1,2"):
    print(f"{r['status']:9} {str(r['source']):6} {r['n']}")
print("季内撞车组数:", len(c.execute("""SELECT season_id,bgm_id FROM items_flat
    WHERE status='included' AND bgm_id IS NOT NULL GROUP BY 1,2 HAVING COUNT(*)>1""").fetchall()))
print("air_date 覆盖:",
      c.execute("SELECT COUNT(*) FROM items_flat WHERE status='included' AND bgm_air_date IS NOT NULL").fetchone()[0], "/",
      c.execute("SELECT COUNT(*) FROM items_flat WHERE status='included' AND bgm_id IS NOT NULL").fetchone()[0])
EOF
```

---

# 1. 拉取 MAL 数据

## 1-2. 【P2】`is_new_anime` 过滤口径

`src/core/season.py:30-35` 只保留 `start_season` 完全等于本季的条目。MAL 偶尔把番标错季度，这部分只能靠 overrides 手工补（`README.md` 的 Override 补番）。暂时不动，但 P0-4 的跨季问题总览做出来后可以回头看看漏了多少。

---

# 2. 运行匹配（规则 + LLM）

## 2-1. 【P1·止血】管线顺序 bug：韩国动画永远不会被跳过

`src/services/openrouter/client.py:31` 的 `SUGGEST_SYSTEM_PROMPT` 第一条规则就是「JA 标题含韩文(한글) → `{"skip":true}`」，但这个调用在管线里排得太靠后。

`src/core/processor.py:288-314` 的实际顺序：

```
_search_bgm() → _try_match()（内含 LLM 匹配）→ 只有失败了才 → suggest_search()（含韩文 skip 规则）
```

BGM 搜索对韩文标题总能搜出点东西，LLM 又常给 ≥0.85 的置信度，于是 `_try_match` 直接 `return True`，**skip 分支永远走不到**。

证据：774 条韩文条目里 292 条被 included，且高度集中在少数 bgm_id：

```
bgm:205216「변신자동차 또봇」被 11 个 MAL 条目占用（2010~2024）
bgm:422501「최강 전사 의 미니 특공대」被 10 个占用
bgm:549170「팡팡 다이노」被 7 个占用
```

**做法**（推荐第一个，零 API 成本）：
- 在 `_process_single` 走搜索**之前**加本地语言护栏：`mal_title_ja` 含谚文（`'가' <= ch <= '힣'`）或纯中文 → 直接 `excluded/rule`；
- 或把 `suggest_search` 的 skip 判定提前到 `_search_bgm` 之前。

## 2-2. 【P1·止血】后缀剥离过度 + exact 匹配不校验日期（撞车主因）

**问题 A**：`src/core/processor.py:44` 的 `re.compile(r"\d+$")` 无条件砍掉标题结尾数字，而 `alternative_keywords`（`processor.py:54-84`）是 while 循环反复剥的：

```
'PSYCHO-PASS 3'                  -> ['PSYCHO-PASS']
'マクロス7'                       -> ['マクロス']
'紙兎ロペ2'                       -> ['紙兎ロペ']
'ドラゴンボールZ'                  -> []                        # 全剥没了
'名探偵コナン 天国へのカウントダウン'  -> ['天国へのカウントダウン']    # 剥成了副标题
```

**问题 B**：`_search_bgm`（`processor.py:418-435`）的降级链会退到 `search_anime_by_keyword_no_date()`（**不带日期过滤**），拿到结果后 `_try_match`（`processor.py:349-360`）只要日文名 NFKC 归一化后相等就 `source='exact'` 直接 included，**完全不校验 air_date**。

于是「紙兎ロペ2」剥成「紙兎ロペ」→ 无日期搜索 → 精确命中初代 → 收录。`bgm:337292`「紙兎ロペ」现在被 13 个 MAL 条目占用。exact 占 included 的 65%（7615 条），这条路径的错误量很大。

**做法**：
1. 干掉裸的 `\d+$`，或只在剩余长度 ≥4 且不是系列编号时才剥；
2. `alternative_keywords` 加保护：剥完后长度 < 原标题一半就丢弃该候选；
3. **剥离后关键词搜出的结果，exact 匹配必须过日期校验** —— air_date 落在季度范围内才允许自动 included，否则降级到 pending 带候选。单这一条就能挡掉大部分撞车；
4. 写入 included 前先查该 bgm_id 是否已被本季/他季占用，是则强制降级 pending。

## 2-3. 【P1】更强的 LLM prompt：喂更多输入（你提的）

现状：
- `MATCH_SYSTEM_PROMPT`（`client.py:20-25`）是为省 token 极限压缩的，候选行只给 `bgm_id:日文名|中文名|日期|简介前 80 字`（`SUMMARY_MAX_CHARS = 80`，`client.py:17`），`max_tokens=128`（`client.py:267`）；
- MAL 侧只给 `英文名|日文名|媒体类型`（`client.py:244-248`）—— **MAL 的 synopsis、studios、start_date、num_episodes 全都没用上**；
- BGM 侧 `Subject` 已经取到了 `summary`/`date`/`platform`/`tags`（`services/bgmtv/client.py:36-47`），但只有 summary 前 80 字进了 prompt，tags/platform 都浪费了。

**前置条件（已满足）**：`mal_anime` 有 `synopsis` / `start_date` / `end_date` / `num_episodes` /
`source` / `studios` / `title_en`，`bgm_subject` 有 `summary` / `platform` / `tags` / `nsfw`。
MAL 侧 fetch 时已写满（`MalClient.FIELDS` 本来就在请求这些字段）；**BGM 侧待 4-3 跑完才有数据，
所以 2-3 必须排在 4-3 之后**。cast 需要额外接口，仍待评估。

**做法**：
1. **扩 prompt 输入**：MAL 侧加首播日期 + 集数 + 简介摘要；BGM 侧 `SUMMARY_MAX_CHARS` 从 80 提到 200~300，加上 `platform`（TV/剧场版/OVA，可直接和 MAL media_type 交叉验证）和高频 tags。**数据都已就位，只差改 prompt 组装。**
2. **加硬规则**：首播日期相差 > 6 个月直接扣分或判否；media_type 与 platform 明显冲突（movie vs TV）判否。这些其实用代码做比让 LLM 做更可靠、更省钱。
3. `max_tokens` 相应放宽，并让模型输出一个简短 `reason` 存进 candidates，人工审核时能看到它为什么这么判。
4. 换更强的模型（当前默认 `deepseek-chat` / `google/gemini-2.5-flash-lite`，`client.py:12-14`），改完 prompt 后拿撞车的那 466 条当回归集验证。
5. 保持系统 prompt 写死为常量（prompt 缓存命中，见 CLAUDE.md）。

## 2-4. 【P2】run 在重复劳动 + 全串行

**A（短路失效）**：`processor.py:267` 的短路条件是 `status='pending' AND source IS NOT NULL`，但库里 1746 条 pending **全是 `source=NULL`** —— 因为 LLM 无匹配时走的是末尾 `source=NULL` 分支（`processor.py:328-332`）。所以短路完全不生效，每次 run 都把这 1746 条的完整搜索链（最多 6 次 BGM 搜索）+ 最多 2 次 LLM 调用**重跑一遍，结果还一样**。

修：末尾 unconfirmed 分支改写 `source='llm'`（或加一个"已尝试过"标记字段），让 Step 4 短路生效，`--retry` 保持强制重跑。注意 `derive_phase`（`src/api/db.py:42-51`）的 `unprocessed` 统计依赖 `source IS NULL`，要一起调整。

**B（串行）**：`process()`（`processor.py:152-163`）逐条 for 循环，BGM 搜索是纯 IO，一季 300 条要十几分钟，100+ 季就是十几小时。改 `ThreadPoolExecutor` 4~8 路并发；共享的 `sqlite3.Connection` 写入要加锁或每线程一个连接。

## 2-5. 【P2】unknown media_type 在源头没堵

`processor.py:285` 的 `except ValueError: pass` 吞掉 `MediaType.from_mal()` 的异常，条目继续走匹配、可能被 included，只在发布时由 `scripts/publish_release.py:52` 静默剔除。应在源头直接 `excluded/rule`（commit 824d03a 只堵了下游）。

---

# 3. 人工审核（pending 队列）

## 3-1. 【P1】`BgmSearch.tsx` 是死代码，无候选条目只能开浏览器手搜

`web/src/components/BgmSearch.tsx` 和后端 `GET /api/bgm/search`（`src/api/routers/bgm.py`）**都完整实现了**，但没有任何页面挂载 `BgmSearch` —— 全仓库只有 `api.ts:95` 和 `types/api.ts:91` 引用它的类型。

影响：108 条无候选的 pending，只能开 bgm.tv 网页手搜再把 ID 抄回输入框。`docs/DESIGN-2026-05-12.md` 的 US-D2 本来就规划了这个交互。

**做法**：在 `ReviewQueue.tsx:257-275` 的手动输入 bgm_id 区域旁挂上 `<BgmSearch seasonId={seasonId} onSelect={...} />`，选中直接填 bgm_id；无候选时默认展开并用 `mal_title_ja` 预填搜索词。

## 3-3. 【P2】`ReviewQueue` 也吃 limit=200 默认值

`ReviewQueue.tsx:35` 调 `getItems` 不传 limit，后端默认 200（`items.py:57`）。当前单季 pending 最多 41 条够用，但和 P0-2 一并修掉。

## 3-4. 【P1·须先于第 7 节】人工决策不记录原因，且 override skip 被伪装成 rule

两个独立但同一次迁移能解决的问题。

**问题 A：`overrides` 的 skip 结果写成 `source='rule'`**（`processor.py:230`）

override skip 的语义是**「MAL 把季度标错了，这条番属于别的季度」**——它和审核界面里的 exclude
不是一回事：exclude 说的是「这个东西在 BGM 侧不成立」，skip 说的是「这个东西成立，但不在这里」。
典型用法是配对操作：A 季度 skip + B 季度 add。

现在把它记成 `source='rule'`，等于把一个**位置错误**伪装成**媒体类型规则过滤**，跑完之后
无法回答「这条是规则踢的还是我手工挪走的」。`origin='override'` 给 add 补了出处，skip 这半边漏了。

**问题 B：exclude / skip 都没有原因字段**

半年后看到一条 `excluded`，无从知道当时是因为 BGM 没收录、还是 BGM 把它并进本篇的额外 ep 了。
自由填空成本太高且很多情况没法分类，所以走**预设枚举 + 可选补充文本**，且**允许不填**。

两组原因几乎不重叠，正好印证 A 里说的语义区别：

| `season_items` 人工 exclude | `overrides` skip |
|---|---|
| `not_on_bgm` BGM 根本没收录 | `wrong_season` MAL 标错季度，该去别的季 |
| `merged_into_ep` BGM 没单列，并进本篇当额外 ep | |
| `not_anime` 媒体类型不该收 | |
| `duplicate` MAL 里重复条目 | |
| `other` + note | |

> 枚举取值是凭现有样例推的，**动手前先按实际跑一遍高频场景补全**，落进 CHECK 之后再加值要新迁移。

**做法**：

1. 新迁移（编号取当时下一个可用值；和 §8 计划的 `004_drop_items.sql` 抢 004，谁先落谁用）：
   ```sql
   ALTER TABLE overrides     ADD COLUMN reason           TEXT;  -- CHECK 枚举
   ALTER TABLE overrides     ADD COLUMN target_season_id TEXT;  -- skip 时可填：它该去哪
   ALTER TABLE overrides     ADD COLUMN note             TEXT;
   ALTER TABLE overrides     ADD COLUMN created_at       TEXT;
   ALTER TABLE season_items  ADD COLUMN reason           TEXT;
   ALTER TABLE season_items  ADD COLUMN note             TEXT;
   -- 顺手补上一直缺的：CHECK(action <> 'add' OR bgm_id IS NOT NULL)
   -- 现在只有 router 在拦（overrides.py:38），CLI/直接 SQL 写进去会让
   -- processor.py:170 的 `bgm_id_ov: int` 拿到 None
   ```
2. `processor.py:230` 的 skip 分支改 `source='human'`，并把 override 的 reason 一并落进 `season_items.reason`。
3. **不要把 override 的 reason 冗余到 `season_items`**（除第 2 步的 skip 落地外）：override 行是 append 的意图记录、不会删，
   `items_flat` 里 `LEFT JOIN overrides` 带出 `override_action` / `override_reason` 即可。
   `origin` 之所以要冗余是因为 add 进来的行必须自证出处，skip 没这个问题。
4. UI：排除按钮做成小 dropdown（4 个预设 + 「其他…」），**不填也能提交**。常见情况零成本，长尾才付文字代价。
5. `target_season_id` 先只当**线索/备忘**用：在 A 季度 skip 时顺手记下「去 2026-summer」，
   将来在 B 季度就能查「有哪些番标记着要挪进来但还没 add」，把隐性的配对操作变成可查询的待办。
   **不做成 `action='move'` 自动跨季写入**——skip 时未必已知 bgm_id，且 B 季度可能还没建，
   run B 时要反扫全库 overrides，复杂度不划算。

**为什么必须排在第 7 节之前**：那次清理会产生 700~1000 条人工 exclude 决策。
字段不存在的话，这批决策的原因**永久丢失**，且正是最需要留档的一批（全是可疑匹配的判定结果）。

⚠️ 不要复用 `season_items.error`——那是「匹配流程失败原因」，只在 pending 时有值，语义完全不同。

---

# 4. 拉取 Bangumi.tv 数据

## 4-3. 【P0 首跑 / P2 并发】`sync-bgm` 不可用于当前规模

`src/api/routers/items.py:124-162` 的 `_run_sync`：
- `WHERE bgm_id IS NOT NULL` **全量**，不支持"只刷 air_date 为空的"增量
- `time.sleep(0.3)` 串行 → 11782 条 ≈ 1 小时
- 无断点续传，中断就白跑
- 只能按单季触发，100+ 季要点 100+ 次

**🔓 拆表已解锁**：待刷队列现在就是一句 `SELECT bgm_id FROM bgm_subject WHERE fetched_at IS NULL`
——天然支持跨季、天然断点续传（拉完就置 `fetched_at`，中断重跑只会捡剩下的），
不需要 `only_missing` 参数这种打补丁的设计。`_run_sync` 也已经改成按 `bgm_id` 去重，
不再对同一条目重复请求。

**剩下要做的**：把触发入口从「单季」改成「全库」，再加并发。当前 11068 条骨架行
（回填时 `fetched_at` 全置 NULL）跑一遍就能把 air_date 覆盖率从 3% 补齐，
顺带把 `bgm_subject` 的 `platform` / `summary` / `tags` / `nsfw` 一次性填满
（字段和写入路径 `ensure_bgm_subject()` 已随拆表就位，纯粹缺数据）。
这四个字段是 2-3 增强 LLM prompt 的输入，5-1 的 `date_mismatch` 也等这一跑。

---

# 5. 人工二次审核（异常数据）

## 5-1. 【P0·最高价值】没有"危险匹配"筛选 —— 700+ 条错误匹配已经审核通过了

`included` 条目在 UI 里全都长一样，没有任何质量维度筛选。而质量问题非常严重且**纯 SQL 就能查出来**：

| 检查项 | 数量 |
|---|---|
| 同一季内 bgm_id 撞车 | 227 组 / 466 条（必然至少一半是错的） |
| 全局 bgm_id 被多条 MAL 占用 | 610 个 id / 1328 条 |
| bgm_air_date 与季度不符 | 跑完 4-3 的增量同步后才有数据（当前覆盖率 3%） |
| included 但 bgm_name 为 NULL | 待查 |
| LLM 置信度刚过阈值（0.85~0.9） | 待查 |

**🔓 拆表已解锁**：这几项现在都是带索引的一句 SQL。`dup_in_season` / `dup_global` 走
`idx_si_bgm`（全局 partial index，不再像旧表那样只有 `(season_id, bgm_id)` 复合索引、
跨季查询要全表扫）；`date_mismatch` 直接 JOIN `bgm_subject.air_date` 和 `seasons` 的
日期范围，不再依赖每行冗余的 `bgm_air_date`——单一来源之后这个检查才有可靠的数据基础。

注意：**不要把撞车做成 UNIQUE 约束**。MAL 拆分 / BGM 合并导致 N:1 和 1:N 现实中都合法，
硬约束会挡掉正确数据。只能是质量视图。

真实样例：

```
2001-spring bgm:2971
  mal:1364  [exact] 名探偵コナン 天国へのカウントダウン → 名探偵コナン 天国へのカウントダウン  ✓
  mal:33150 [llm]   名探偵コナン ピラミッドからの挑戦状! → 名探偵コナン 天国へのカウントダウン  ✗

bgm:337292「紙兎ロペ」被 13 个 MAL 条目占用（2009~2019，全是 CM/コラボ 短片）
```

**做法**：
1. 后端新增 `GET /api/seasons/{id}/issues`（或给 `list_items` 加 `issue=` 参数），判定逻辑放 SQL / 新建 `src/api/quality.py`：
   - `dup_in_season`：同季 bgm_id 出现 > 1 次
   - `dup_global`：该 bgm_id 在其他季度也被 included
   - `date_mismatch`：`bgm_air_date` 超出季度范围（复用 `ItemList.tsx:31-58` 的 `isDateOutOfRange`，**建议下沉到后端统一口径**）
   - `no_bgm_name`：included 但 bgm_name 为空
   - `low_confidence`：0.85 ≤ confidence < 0.9
2. `ItemList` 加第三行 tab：`全部 / ⚠重复 / ⚠日期不符 / ⚠低置信`，卡片上给 issue 打红色 badge。
3. 加**跨季度全局问题总览页**（首页或 `/issues`），否则 100+ 季要一个个点进去。

## 5-2. 【P0】标记后整页刷新，滚动位置丢失（原 todo #1）

`web/src/components/ItemList.tsx:274-277` 的 `onUpdated` 调 `loadItems()` 全量重载并 `setLoading(true)`，整个列表卸载重建，滚动位置归零。

参照：`ReviewQueue.tsx:71-102` 已经是乐观更新（先改本地 state，失败用 snapshot 回滚）；`ItemList.tsx:73-84` 的 `syncItem` 也已经是局部替换的写法，直接抄。

**做法**：
1. `ItemEditModal` 的 `onUpdated` 改为接收更新后的 item，`ItemList` 用 `setItems(prev => prev.map(it => it.mal_id === updated.mal_id ? updated : it))` 局部替换（`api.patchItem` 的返回值就是更新后的 item）。
2. 加**行内快捷操作**：现在改一条要「点卡片 → 开 modal → 选排除 → 点确认 → 整页重载」4 次交互，卡片右侧加 ✗（排除）/ ↺（打回 pending）按钮即可一次搞定。
3. 可选：列表键盘导航（j/k 移动、x 排除）—— 二次审核是最高频操作。

## 5-3. 【P0】`ItemList` 静默截断，51 个季度看不全

`web/src/services/api.ts:53-66` 的 `getItems` 不传 limit，后端 `src/api/routers/items.py:57` 默认 `limit=200`。

51 个季度条目数 > 200（最大 339）→ 最多 139 条条目在 UI 上**根本不存在**，无分页无提示。第 5 步二次审核天然漏掉这部分。

**做法**：最省事是 `ItemList` 显式传 `limit: 1000`；正规做法是后端返回 total、前端分页或无限滚动。

---

# 6. 跨章节 / 杂项

- **`src/main.py:18` `END_YEAR = 2025` 硬编码** → 2026 各季不在批处理范围。改成动态取当前年份或从 DB 已有季度推。【P2】
- **单个 sqlite Connection 跨线程共享**：`app.state.db` 同时被 FastAPI 主线程和 executor 线程（`run.py:91`、`items.py:215`）读写，长任务期间存在交错风险。做 2-4 并发时一并处理。【P2】
- **`src/core/models.py` 的 `ConfirmStatus` 8 状态枚举是死代码**（只被 release 用的旧 dataclass 引用，不参与 DB 流程），可连同 `StateItem`/`StateData` 一起删。【P2】
- **提交纪律**：任何改动 DB 的工作结束后跑 `uv run python scripts/export_decisions.py` 再提交（`data: YYYY-MM-DD HH:MM`）。快照只含不可重建的决策，MAL / BGM 事实随时能重拉。
- **破坏性操作前**先 `VACUUM INTO 'backups/season-<日期>.db'`（`backups/` 已 gitignore）。§7 的批量打回属于此列。

---

# 7. 做完止血后的一次性数据清理

2-1 / 2-2 只能阻止**新增**错配，历史上已写进 `included` 的错误要单独清：

1. 用 5-1 的质量检查列出全部 `dup_in_season`（466 条）+ 韩文 included（292 条）+ `dup_global`（1328 条，去重后）；
2. 批量打回 `pending`（`PATCH action=pending` 会清空 bgm_id/name，见 `items.py:103-107`）；
3. 修完 2-2 后重跑 `run --retry`，让新逻辑重新匹配；
4. 剩下的进人工审核队列；
5. 重跑 `export_decisions.py` 并提交。

**动手前先 `VACUUM INTO 'backups/season-<日期>.db'`** —— 这是唯一会大批量改写决策列的操作。

预估影响范围：约 700~1000 条 included 需复核，占总量 6~8%。

---

# 8. 优先级执行顺序

> **2026-08-03 更新**：`dev.md` 的数据库重构已完成（拆表 + 抛弃 `data/`），
> 由此解决的条目（原 1-1 / 3-2 / 4-1 / 4-2）已从本文件删除。
> **4-3** / **5-1** / **2-3** 的阻塞随之解除，见各条目里的「🔓 拆表已解锁」。
>
> **主线依赖**：`5-3 → 5-2`（能看全 + 改得动）→ `4-3`（有数据）→ `5-1`（能筛出问题）
> → `2-1 / 2-2`（止血，否则清完又脏）→ `3-4`（有地方记原因）→ **§7 清理** → `2-3`（提质）。
> 这条链上每一步都是下一步的前提，不要跳。

## P0 — 立刻（做完才能正常干活）

| 顺序 | 任务 | 成本 | 收益 |
|---|---|---|---|
| 1 | **5-3** `getItems` limit / 分页 | 10min | 补回 51 个季度看不见的条目 |
| 2 | **5-2** `ItemList` 乐观更新 + 行内操作 | 半天 | 直接解决滚动丢失，二次审核 4 次交互 → 1 次 |
| 3 | **4-3** 全库跑一次增量 sync-bgm（先只做「全库触发」，并发留 P2） | 1h + 等 | 补齐 97% 缺失的 air_date；解锁 5-1 的 `date_mismatch` 和 2-3 的 BGM 侧输入 |
| 4 | **5-1** 质量检查 API + UI 筛选 | 半天 | 一次性揪出 700+ 已有错误 |

## P1 — 止血（不做完不值得大批量审核，否则清完又被新错配弄脏）

| 顺序 | 任务 | 成本 |
|---|---|---|
| 5 | **2-1** 语言护栏（韩文/纯中文直接 excluded） | 1h |
| 6 | **2-2** 收窄后缀剥离 + exact 加日期校验 + 撞车前置检查 | 半天 |
| 7 | **3-1** 挂载 `BgmSearch`（§7 清理后审核队列会暴涨，先把无候选的路打通） | 1h |
| 8 | **3-4** 决策原因迁移 + skip 的 `source='rule'` 修正 | 半天 |

> **8 必须在 §7 之前**：那次清理产生 700~1000 条人工 exclude，
> 字段不存在的话这批原因永久丢失，而它们恰恰是最值得留档的一批。

## 一次性清理

| 顺序 | 任务 | 成本 |
|---|---|---|
| 9 | **第 7 节** 打回 700~1000 条问题 included，用新逻辑重跑 | 半天 + 机器时间 |

## P1.5 — 清理之后

| 顺序 | 任务 | 成本 |
|---|---|---|
| 10 | **2-3** 增强 LLM prompt（依赖 4-3 填满 BGM 侧字段；拿撞车的 466 条当回归集） | 1 天 |

## P2 — 规模化（批处理 100+ 季之前）

| 顺序 | 任务 | 成本 |
|---|---|---|
| 11 | **2-4** run 短路修复 + 并发 | 1 天 |
| 12 | **4-3** 余下部分：sync-bgm 并发 | 2h |
| 13 | **1-2** `is_new_anime` 过滤口径复查（等 5-1 的跨季总览出来后回头看漏了多少） | 待定 |
| 14 | **2-5 / 3-3 / 6** unknown media_type 源头拦截、`ReviewQueue` limit、END_YEAR、连接隔离、删死代码 | 半天 |
| 15 | **`00N_drop_items.sql`** 确认新 schema 稳定后删掉冻结的旧 `items` 表（注意和 3-4 的迁移抢编号） | 10min |
