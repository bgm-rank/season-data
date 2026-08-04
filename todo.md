# TODO — 季度数据流程改进

> 2026-08-03 全流程 review 产出。写得比较详细，目的是让新会话不用重读代码/查库就能直接动手。
> 结论：手感问题只是表象，真正的问题是**第 4、5 步事实上没跑起来**，且有几个静默 bug 在持续破坏数据 / 制造错误匹配。
> 章节按你的五步流程组织；文末有跨章节的优先级执行顺序。
> 已完成的条目直接删除，不再保留划线记录（病因需要留档的写进 commit message）。条目编号保持稳定，删了不重排。
> **2026-08-04**：P0 四项（5-3 / 5-2 / 4-3 首跑 / 5-1 质量检查）已完成并测试，见 commit `b03191e`，相应条目已删。
> **2026-08-04（二）**：2-1 语言护栏已完成，但原文两条做法经实测否决 —— 详见 §8 的更新块，动手前务必先看。
> **2026-08-04（三）**：2-3 已完成（high/low 双 prompt + 代码侧硬规则），顺带挖出两个 live bug
> 和一次全库回填 —— 详见 §8 的更新块。**注意 §7 清理的目标集因此扩大**：硬规则在
> `included/llm` 上命中 637 条（15.5%），抽样几乎全是真错配，可直接当打回名单。

## 现状体检（2026-08-03 基线，air_date / issue 数据为 2026-08-04 复测）

```
季度总数 108，其中 95 个季度仍有 pending
included 11796  (exact 7615 / llm 4119 / human 48)
excluded  7054  (rule  6321 / llm  613 / human 134)
pending   1746  (全部 source=NULL；1638 条有候选，108 条无候选，0 条带 error)

bgm_air_date 覆盖率： 11720 / 11776 included = 99.5%（4-3 全库同步已跑完，剩 2 条骨架行）
mal_anime 扩展字段： 20587 / 20607 = 99.9%（2026-08-04 backfill_mal.py 跑完，此前只有 80 行）
硬规则命中(2-3)：    included/llm 637 / 4113 = 15.5%，included/exact 106 / 7615 = 1.4%
质量检查全库命中：    dup_in_season 463 / dup_global 914 / date_mismatch 810 / no_bgm_name 0
韩文标题条目：        774 条，其中 288 条被 included（llm 156 全错 / exact 132 全对，见 2026-08-04(二) 更新）
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

`src/core/season.py:30-35` 只保留 `start_season` 完全等于本季的条目。MAL 偶尔把番标错季度，这部分只能靠 overrides 手工补（`README.md` 的 Override 补番）。暂时不动，但 5-1 的跨季问题总览做出来后可以回头看看漏了多少。

---

# 2. 运行匹配（规则 + LLM）

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

## 4-3. 【P2】`sync-bgm` 并发

全库增量同步已落地为 `scripts/sync_bgm.py`（队列 = `bgm_subject.fetched_at IS NULL`，
天然断点续传），首跑也已完成：air_date 覆盖率 3% → 99.5%，`platform` / `summary` /
`tags` / `nsfw` 一并填满，2-3 的 BGM 侧输入和 5-1 的 `date_mismatch` 由此解锁。

**剩下的**：`sync_subjects()`（`src/core/bgm_sync.py`）仍是 `time.sleep(0.3)` 串行，
下次大批量刷新（如重跑 §7 后的新 bgm_id）还是要一两个小时。改并发时注意 API 侧
`_run_sync` 与主线程共用同一个 sqlite Connection，见 §6 的连接隔离条目。

---

# 5. 人工二次审核（异常数据）

## 5-1. 【P1】质量检查缺跨季度总览页

单季的质量检查已完成：`src/api/quality.py` 提供 `dup_in_season` / `dup_global` /
`date_mismatch` / `no_bgm_name` 四项判定，`GET /seasons/{id}/items?issue=` 支持筛选并回
`issue_counts`，`ItemList` 有 issue tab + 卡片 badge。全库命中见文首体检块。

`low_confidence`（0.85 ≤ confidence < 0.9）**故意没做**：实测这个区间 0 条——
阈值就是 0.85，LLM 给的分基本落在 0.9 以上，这条筛选没有信息量。

**剩下的**：加**跨季度全局问题总览页**（首页或 `/issues`），否则 108 个季度要一个个点进去
才知道哪些季度有问题。§7 的一次性清理需要它来定位目标季度，也可以直接拿 SQL 跑一遍
清单代替（见文首体检块的统计脚本），做不做取决于清理时的手感。

注意：**不要把撞车做成 UNIQUE 约束**。MAL 拆分 / BGM 合并导致 N:1 和 1:N 现实中都合法，
硬约束会挡掉正确数据。只能是质量视图。

真实样例：

```
2001-spring bgm:2971
  mal:1364  [exact] 名探偵コナン 天国へのカウントダウン → 名探偵コナン 天国へのカウントダウン  ✓
  mal:33150 [llm]   名探偵コナン ピラミッドからの挑戦状! → 名探偵コナン 天国へのカウントダウン  ✗

bgm:337292「紙兎ロペ」被 13 个 MAL 条目占用（2009~2019，全是 CM/コラボ 短片）
```

---

# 6. 跨章节 / 杂项

- **`season_items.confidence` 大面积为 0**（2026-08-04 做 2-1 时顺手发现）：`included/llm` 共 4113 条，
  其中 **4081 条 `confidence=0.0`**。绝大部分是 2026-05 那次一次性导入的遗留（`updated_at` 时间戳完全相同，
  旧 `data/` JSON 时代压根没存 confidence），不是 live bug —— 2026-06 写入的 25 条都是 ≥0.85。
  **但 2026-07 有 46 条、2026-08 有 30 条又是 `=0`**，这批得单独查一次是不是 live bug。
  影响面：`confidence` 现在无法用来筛可疑匹配（5-1 的 `low_confidence` 判定「实测 0 条」很可能就是被这个掩盖了，
  而不是真的没有）。查证脚本见下。【P2】

  ```bash
  uv run python - <<'EOF'
  import sqlite3
  c = sqlite3.connect('season.db'); c.row_factory = sqlite3.Row
  for r in c.execute("""SELECT substr(updated_at,1,7) ym,
    SUM(CASE WHEN confidence>=0.85 THEN 1 ELSE 0 END) hi,
    SUM(CASE WHEN confidence=0 THEN 1 ELSE 0 END) zero, COUNT(*) n
    FROM season_items WHERE status='included' AND source='llm'
    GROUP BY 1 ORDER BY 1 DESC LIMIT 12"""):
      print(f"{r['ym']}  >=0.85:{r['hi']:5}  =0:{r['zero']:5}  总:{r['n']}")
  EOF
  ```

- **`src/main.py:18` `END_YEAR = 2025` 硬编码** → 2026 各季不在批处理范围。改成动态取当前年份或从 DB 已有季度推。【P2】
- **单个 sqlite Connection 跨线程共享**：`app.state.db` 同时被 FastAPI 主线程和 executor 线程（`run.py:91`、`items.py:215`）读写，长任务期间存在交错风险。做 2-4 并发时一并处理。【P2】
- **`src/core/models.py` 的 `ConfirmStatus` 8 状态枚举是死代码**（只被 release 用的旧 dataclass 引用，不参与 DB 流程），可连同 `StateItem`/`StateData` 一起删。【P2】
- **提交纪律**：任何改动 DB 的工作结束后跑 `uv run python scripts/export_decisions.py` 再提交（`data: YYYY-MM-DD HH:MM`）。快照只含不可重建的决策，MAL / BGM 事实随时能重拉。
- **破坏性操作前**先 `VACUUM INTO 'backups/season-<日期>.db'`（`backups/` 已 gitignore）。§7 的批量打回属于此列。

---

# 7. 做完止血后的一次性数据清理

2-1 / 2-2 只能阻止**新增**错配，历史上已写进 `included` 的错误要单独清：

1. 用 5-1 的质量检查列出全部 `dup_in_season`（463 条）+ `date_mismatch`（810 条）+ 韩文 `included/llm`（156 条）+ `dup_global`（914 条，与前几项有重叠）；
   ⚠️ **韩文只打回 `source='llm'` 那 156 条**，`source='exact'` 的 132 条是正确匹配（BGM 以谚文原名收录韩国动画，标题严格相等），不要碰。打回后重跑会走 2-1 的语言护栏，无精确匹配的一律 `excluded/rule`；
   ➕ **另加 2-3 硬规则的命中集**（2026-08-04 实测，`included/llm` 637 条 / `included/exact` 106 条），
   抽样准确率远高于 `date_mismatch`。名单用 `core.processor.match_conflicts()` 现算即可：
   ```bash
   uv run python - <<'EOF'
   import sqlite3, sys; sys.path.insert(0, 'src')
   from core.processor import match_conflicts
   from services.bgmtv import Subject
   c = sqlite3.connect('season.db'); c.row_factory = sqlite3.Row
   for r in c.execute("""SELECT si.season_id, si.mal_id, si.source, m.start_date, m.media_type,
       b.air_date, b.platform FROM season_items si JOIN mal_anime m USING(mal_id)
       LEFT JOIN bgm_subject b ON b.bgm_id=si.bgm_id WHERE si.status='included'"""):
       cf = match_conflicts(r["start_date"], r["media_type"],
                            Subject(id=0, type=2, date=r["air_date"], platform=r["platform"]))
       if cf: print(r["season_id"], r["mal_id"], r["source"], cf)
   EOF
   ```
2. 批量打回 `pending`（`PATCH action=pending` 会清空 bgm_id/name，见 `items.py:103-107`）；
3. 修完 2-2 后重跑 `run --retry`，让新逻辑重新匹配；
4. 剩下的进人工审核队列；
5. 重跑 `export_decisions.py` 并提交。

**动手前先 `VACUUM INTO 'backups/season-<日期>.db'`** —— 这是唯一会大批量改写决策列的操作。

预估影响范围：约 700~1000 条 included 需复核，占总量 6~8%；
加上 2-3 硬规则命中集（743 条，与 `date_mismatch` 有大量重叠）后上限约 1200 条。

---

# 8. 优先级执行顺序

> **2026-08-03 更新**：`dev.md` 的数据库重构已完成（拆表 + 抛弃 `data/`），
> 由此解决的条目（原 1-1 / 3-2 / 4-1 / 4-2）已从本文件删除。
>
> **2026-08-04 更新**：P0 四项全部完成（commit `b03191e`）——
> 5-3（分页 + total）、5-2（乐观更新 + 行内操作 + 键盘导航）、3-3（顺手修）、
> 4-3 首跑（air_date 3% → 99.5%）、5-1 质量检查 API + UI 筛选。P0 表已删。
> 5-1 只剩跨季总览页、4-3 只剩并发，均已降级。
>
> **2026-08-04（二）**：2-1 语言护栏已完成，但**实现范围比原文窄，两条原方案经实测否决**：
> - **中文护栏否决**。「无假名 + 含非 JIS 汉字（简体字）」全库命中 1618 条，1292 条已 included，
>   抽样几乎全是**正确匹配**的国产动画（罗小黑战记、秦时明月之百步飞剑、哪吒传奇、潜艇总动员…），
>   BGM 侧确实以中文原名收录，其中 955 条是 `source='exact'`（标题严格相等）。本地排除等于销毁正确数据。
>   更朴素的「无假名→中文」判据更不能用：命中 3768 条，里面是犬夜叉 / 攻殻機動隊 / 十二国記 / 灰羽連盟。
>   **别再提这条。**
> - **韩文不一刀切**。775 条谚文条目里 `exact` 的 132 条**全对**、`llm` 的 156 条**全错**（44 组撞车）。
>   错配 100% 来自 LLM 分支，所以护栏是「掐 LLM、保留 exact」：谚文标题不进 `match_anime` 也不进
>   `suggest_search`，精确匹配失败直接 `excluded/rule`（日志 `[lang guard]`）。零 LLM 调用。
>   判据 `is_korean_title()` 要求含谚文**且不含假名**，否则会误伤「ブルーアーカイブ / 블루 아카이브」这类日韩混排。
>
> **2026-08-04（三）**：2-3 完成，实现与原文一致（high/low 双 prompt + 硬规则 + reason），
> 但过程中挖出的三件事比 prompt 本身更值钱：
> - **`mal_anime` 扩展字段全库是空的**。原文写「MAL 侧 fetch 时已写满」是错的：003 拆表只搬了
>   4 列，之后没重新 fetch 过的季度一直空着——20607 行里只有 80 行有 `start_date`。
>   即是说 high 模式的 MAL 侧输入和日期硬规则本来会全程空转。已加 `scripts/backfill_mal.py`
>   （只写 mal_anime 这张缓存表，不碰决策）并跑完全库：覆盖率 0.4% → 99.9%，耗时 204s。
> - **`max_tokens` 对推理模型是致命的**。`google/gemini-3.6-flash` 的 reasoning_tokens
>   （实测 122~244）也算进 `max_tokens`，旧的 `match_anime=128` / `suggest_search=64`
>   让输出在 JSON 写完前就 `finish_reason=length` 被砍断，解析失败后**静默当成「无匹配」**——
>   钱照付、结果全丢。这多半就是 2-4 说的「1746 条 pending 全是 source=NULL」的一大来源。
>   已改成 768/1024/512 并在截断时打 WARNING；`extract_json` 也补了未闭合围栏的处理。
> - **硬规则的命中率远超预期**：`included/llm` 4113 条里命中 637 条（15.5%，date 562 / platform 174），
>   `included/exact` 7615 条里命中 106 条（1.4%）。抽样看几乎全是真错配
>   （School Days ONA→TV 2007、滋賀ッツマン→あずまんが大王、オモヒデ→おもひでぽろぽろ 1991）。
>   **这就是 §7 现成的打回名单**，比原计划的 dup/date_mismatch 组合更准。
>   注意硬规则只拦新写入，这 637 条历史数据得靠 §7 打回重跑才会被纠正
>   （已在副本上验证：打回后重跑，错配的那几条新逻辑要么给 pending 要么直接判无匹配）。
>
> **主线依赖**：~~5-3 → 5-2 → 4-3 → 5-1 → 2-1 → 2-3~~（已完成）
> → `2-2`（止血，否则清完又脏）→ `3-4`（有地方记原因）→ **§7 清理**。
> 这条链上每一步都是下一步的前提，不要跳。
> 2-3 提前做掉是因为它不改决策逻辑、只改输入质量，且 §7 重跑时要靠它提质。

## P1 — 止血（不做完不值得大批量审核，否则清完又被新错配弄脏）

| 顺序 | 任务 | 成本 |
|---|---|---|
| 6 | **2-2** 收窄后缀剥离 + exact 加日期校验 + 撞车前置检查 | 半天 |
| 7 | **3-1** 挂载 `BgmSearch`（§7 清理后审核队列会暴涨，先把无候选的路打通） | 1h |
| 8 | **3-4** 决策原因迁移 + skip 的 `source='rule'` 修正 | 半天 |
| 8.5 | **5-1 剩余** 跨季度问题总览页（也可用 SQL 清单代替，看清理时的手感） | 2h |

> **8 必须在 §7 之前**：那次清理产生 700~1000 条人工 exclude，
> 字段不存在的话这批原因永久丢失，而它们恰恰是最值得留档的一批。

## 一次性清理

| 顺序 | 任务 | 成本 |
|---|---|---|
| 9 | **第 7 节** 打回 700~1000 条问题 included，用新逻辑重跑 | 半天 + 机器时间 |

## P2 — 规模化（批处理 100+ 季之前）

| 顺序 | 任务 | 成本 |
|---|---|---|
| 11 | **2-4** run 短路修复 + 并发 | 1 天 |
| 12 | **4-3** sync-bgm 并发 | 2h |
| 13 | **1-2** `is_new_anime` 过滤口径复查（等 5-1 的跨季总览出来后回头看漏了多少） | 待定 |
| 14 | **2-5 / 6** unknown media_type 源头拦截、END_YEAR、连接隔离、删死代码 | 半天 |
| 15 | **`00N_drop_items.sql`** 确认新 schema 稳定后删掉冻结的旧 `items` 表（注意和 3-4 的迁移抢编号） | 10min |
