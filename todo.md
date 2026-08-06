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
> 同日重写 2-2：原诊断（后缀剥离 + exact 不校验日期是撞车主因）经数据检验不成立，
> 撞车主要来自 LLM 而非 exact，且剥离根本不参与判等。**后缀剥离任何时候都不要动。**
> **2026-08-05**：**2-2（序号护栏）、3-1（挂载 BgmSearch）、5-1 剩余（跨季总览页）整条删除**，
> 都改为交给人工，不再写代码。否决依据见 §8 的更新块——尤其别再重新提序号护栏。
> **2026-08-05（二）**：3-4 已完成（004 迁移 + 原因选择器），**P1 止血环节到此结束，下一步直接进 §7**。
> 两处偏离原方案，详见 §8 的更新块：`reason` 没落 CHECK；`overrides` 的
> `CHECK(action <> 'add' OR bgm_id IS NOT NULL)` **判定为不能加**，别再提。
> **2026-08-06**：2026-winter 全量打回重跑 + 人工审完（见 §8 更新块）。过程中确认了一件
> 会改写 §7 前提的事：**108 个季度里 99 个是 2026-05-12 的一次性导入产物，从未经这套管线跑过**。
> §7 原本按「打回问题条目」设计，实际规模是「99 个季度全量重跑」。冬季这一季的实测收益见 §7 的更新块。

## 现状体检（2026-08-03 基线，air_date / issue 数据为 2026-08-04 复测）

```
季度总数 108，其中 95 个季度仍有 pending
included 11796  (exact 7615 / llm 4119 / human 48)
excluded  7054  (rule  6321 / llm  613 / human 134)
pending   1746  (全部 source=NULL；1638 条有候选，108 条无候选，0 条带 error)

bgm_air_date 覆盖率： 11720 / 11776 included = 99.5%（4-3 全库同步已跑完，剩 2 条骨架行）
mal_anime 扩展字段： 20587 / 20607 = 99.9%（2026-08-04 backfill_mal.py 跑完，此前只有 80 行）
硬规则命中(2-3)：    included/llm 637 / 4113 = 15.5%，included/exact 106 / 7615 = 1.4%
撞车按 source 拆：   llm 881 行 = llm 的 21.4%；exact 430 行 = exact 的 5.6%（llm 是 exact 的 3.8 倍）
序号护栏(原 2-2)：   25 条，其中 19 条已被 2-3 硬规则覆盖，独有 6 条里 3 条是误报 → 已否决
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

`src/core/season.py:30-35` 只保留 `start_season` 完全等于本季的条目。MAL 偶尔把番标错季度，这部分只能靠 overrides 手工补（`README.md` 的 Override 补番）。暂时不动，等 108 季逐季 review 走完一遍后回头看看漏了多少。

---

# 2. 运行匹配（规则 + LLM）

## 2-6. 【P2】exact 分支的日期校验

`_search_bgm` 的降级链会退到 `search_anime_by_keyword_no_date()`，exact 命中后不校验 air_date。
`included/exact` 7630 条里 430 条卷入撞车（5.6%），2-3 的硬规则另在其中命中 106 条日期/类型冲突。
量级比 llm 侧小得多，但同名不同作（重制、同名剧场版）确实存在，值得补。
做法：exact 命中后同样跑一遍 `match_conflicts()`，有冲突就降级 pending 而不是直接 included。

## 2-4. 【P2】run 在重复劳动 + 全串行

**A（短路失效）**：`processor.py:267` 的短路条件是 `status='pending' AND source IS NOT NULL`，但库里 1746 条 pending **全是 `source=NULL`** —— 因为 LLM 无匹配时走的是末尾 `source=NULL` 分支（`processor.py:328-332`）。所以短路完全不生效，每次 run 都把这 1746 条的完整搜索链（最多 6 次 BGM 搜索）+ 最多 2 次 LLM 调用**重跑一遍，结果还一样**。

修：末尾 unconfirmed 分支改写 `source='llm'`（或加一个"已尝试过"标记字段），让 Step 4 短路生效，`--retry` 保持强制重跑。注意 `derive_phase`（`src/api/db.py:42-51`）的 `unprocessed` 统计依赖 `source IS NULL`，要一起调整。

**B（串行）**：`process()`（`processor.py:152-163`）逐条 for 循环，BGM 搜索是纯 IO，一季 300 条要十几分钟，100+ 季就是十几小时。改 `ThreadPoolExecutor` 4~8 路并发；共享的 `sqlite3.Connection` 写入要加锁或每线程一个连接。

## 2-5. 【P2】unknown media_type 在源头没堵

`processor.py:285` 的 `except ValueError: pass` 吞掉 `MediaType.from_mal()` 的异常，条目继续走匹配、可能被 included，只在发布时由 `scripts/publish_release.py:52` 静默剔除。应在源头直接 `excluded/rule`（commit 824d03a 只堵了下游）。

---

# 3. 人工审核（pending 队列）

## 3-5. 【P2】LLM 的 `reason` 在审查界面基本看不到

2-3 让模型在 high 模式下给出判定理由，写进 `season_items.candidates` 的 `reason` 键，
`CandidatePanel.tsx` 也渲染了。**但审查队列里绝大多数条目根本看不到它**：

pending 条目的候选有两个来源，只有第二种带 reason ——
1. `_process_single` 末尾的 `[unconfirmed]` 分支（模型说「都不匹配」，只把搜索结果列出来），
   `source=NULL`，candidates 里**没有 reason 键**。库里 1746 条 pending 全是这一种。
2. `_try_match` 的 LLM 分支给了匹配但 confidence < 0.85，或被硬规则降级（`source='llm'`）。
   这种才有 reason + conflicts，但数量少得多。

即是说，最需要解释的那一类（「模型为什么一个都不选」）恰恰是没有解释的。

**做法**（任选，成本递增）：
1. 让 high 模式的 prompt 在返回空数组时也附一句总体理由（改成
   `{"matches": [...], "note": "..."}`，无匹配时 note 说明为什么），存进 `season_items.error`
   或 candidates 的同级字段；
2. 或者退一步，把「模型判过且认为都不匹配」这个事实本身显示出来
   （现在 `source=NULL` 和「压根没跑过」无法区分——这正是 2-4 A 要修的短路问题，
   两件事可以一起做：末尾分支改写 `source='llm'` 后，UI 就能区分「没跑」和「跑了没结果」）。

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

## 现状（本节已无待办，留作参考）

单季的质量检查已完成：`src/api/quality.py` 提供 `dup_in_season` / `dup_global` /
`date_mismatch` / `no_bgm_name` 四项判定，`GET /seasons/{id}/items?issue=` 支持筛选并回
`issue_counts`，`ItemList` 有 issue tab + 卡片 badge。全库命中见文首体检块。
**撞车的发现全靠这套事后视图**（2026-08-05 删 2-2 时定的：不在写入路径上加撞车判定）。

`low_confidence`（0.85 ≤ confidence < 0.9）**故意没做**：实测这个区间 0 条——
阈值就是 0.85，LLM 给的分基本落在 0.9 以上，这条筛选没有信息量。

**跨季度总览页已于 2026-08-05 否决**（原 5-1 的剩余部分），理由见 §8 更新块。
需要跨季清单时直接跑文首体检块的 SQL。

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
  ~~**但 2026-07 有 46 条、2026-08 有 30 条又是 `=0`**，这批得单独查一次是不是 live bug。~~
  **2026-08-06 查完了：不是 live bug。** 那 76 条（2023-fall 46 / 2024-fall 30）的 `candidates`
  全部缺 `air_date` 键，说明决策本体是 05-12 导入的，只有 `updated_at` 被后来某个不改决策的
  写路径刷新过——详见 §7 的 2026-08-06 更新块。对照组：08-06 冬季重跑写入的 25 条 `included/llm`
  **confidence 全部 ≥ 0.85、candidates 全部带 `air_date`**。所以 `confidence` 对**新写入**的行是可信的，
  只是全库仍被 3981 条导入遗留污染，等 §7 重跑完自然消失。
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

> **2026-08-06 更新（先看这块，它改了本节的前提和做法）**
>
> **前提变了：99 / 108 个季度是 2026-05-12 的一次性导入，从未跑过这套管线。**
> 判据是「整季只有 1 个 `updated_at` 值」——真跑过 `run` 的季度每条时间戳都不同：
>
> ```bash
> uv run python - <<'EOF'
> import sqlite3
> c = sqlite3.connect('file:season.db?mode=ro', uri=True); c.row_factory = sqlite3.Row
> for r in c.execute("""SELECT season_id, count(*) n, count(DISTINCT updated_at) d
>     FROM season_items GROUP BY 1 HAVING d > 3 ORDER BY season_id"""):
>     print(f"{r['season_id']:<14} {r['n']:>3} 条  {r['d']:>3} 个时间戳")   # 只有这些跑过
> EOF
> ```
> 目前跑过的只有 9 个：2000-spring / 2001-winter / 2023-summer / 2023-fall / 2024-fall / 2026 四季。
>
> **`updated_at` 不能当「决策何时产生」用。** 76 条 `included/llm confidence=0` 的
> `updated_at` 显示是 07-31 / 08-03（2023-fall 46 条、2024-fall 30 条），看着像 live bug，
> 但它们的 `candidates` **缺 `air_date` 键**——现行代码和 07-31 当时的 `0e0f38a` 都会写这个键，
> 所以决策本体是 05-12 导入的，只是 `updated_at` 后来被某个不改决策的写路径刷新了。
> 要判「这条决策是不是这套管线产出的」，看 `candidates` 里有没有 `air_date` / `reason` 键，别看时间戳。
>
> **做法改成「整季打回 + 重跑」，不再挑条目打回。** 注意 **`--retry` 单独用没有效果**：
> `_process_single` 的 Step 2 对 `included` / `excluded` 无条件 `return`，`retry` 只影响
> Step 4 那个「pending 且 source 非空」的短路。必须两步：先 `UPDATE ... SET status='pending',
> source=NULL, bgm_id=NULL, confidence=NULL, candidates=NULL, error=NULL, reason=NULL, note=NULL`
> （字段范围抄 `items.py` 的 `action='pending'` 分支），再跑 `run --retry`。
>
> **冬季实测（215 条，5 分钟，1 次全季 LLM）**：
> - `bgm_id` 变更 **0 条**——老的 98 exact + 24 llm 全部原样重现，重跑无回归风险
> - 纠错 **12 条**：1 条降级（63142 韩文错配 → 语言护栏 `excluded/rule`）、
>   11 条升级（10 条 fetch 后没跑过的新条目自动 exact 命中 + 63426「熊熊帮帮团4」
>   从被误标的 `excluded/rule` 恢复成 `included/exact` bgm:639425）
> - 人工只需处理 **6 条**（全是 BGM 未收录的宣传片 / 特别篇），耗时几分钟
> - 重跑后 `match_conflicts()` 命中 0、`dup_in_season` 0、`date_mismatch` 0
>
> 即是说单季成本远低于原估的「半天」，瓶颈是 LLM 调用的墙钟时间（→ 2-4 的并发）。
> 按冬季的比例外推，99 个季度约 2.4 万条，其中需要人工的量级在 2000~3000 条。

2-1 / 2-3 只能阻止**新增**错配，历史上已写进 `included` 的错误要单独清：

1. 用 §5 的质量检查（`src/api/quality.py`）列出全部 `dup_in_season`（463 条）+ `date_mismatch`（810 条）+ 韩文 `included/llm`（156 条）+ `dup_global`（914 条，与前几项有重叠）；
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
3. 重跑 `run --retry`，让 2-1 语言护栏 + 2-3 硬规则 + high prompt 重新匹配；
4. 剩下的进人工审核队列——排除时顺手点一下原因 chip（3-4 已落地，审核队列和编辑弹窗都有，
   不填也能提交）。这一步正是 3-4 存在的理由，别嫌麻烦跳过；
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
> 5-1 只剩跨季总览页（已于 08-05 否决）、4-3 只剩并发。
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
> **2026-08-05**：**2-2（序号护栏）与 3-1（挂载 BgmSearch）整条删除，都改为交给人工。**
> - **2-2 否决**。起因是复查「high 模式多喂信息能不能替代序号护栏」，先纠正一个前提：
>   `_build_match_input`（`client.py:316`）里 MAL 的罗马字主标题 `MalBrief.title` **low / high 都送**，
>   high 在标题这一维度是零增量，增量全在 start_date / num_episodes / source / studios / synopsis
>   与 BGM 侧 platform / tags / 长简介。所以「high 送了英文名所以能判季数」这个说法不成立。
> - 更要命的是**送了也没用**：把 todo 原文的 `split_ordinal` 模式表实现出来跑全库，
>   命中 25 条（仍是 100% `source='llm'`），其中 **23 条的 MAL 英文标题自带季数**
>   （`Byeonsinjadongcha Tobot 18th Season` → 光杆「변신자동차 또봇」，
>   `Kamiusagi Rope 2` → 「紙兎ロペ」）。信息一直都在 prompt 里，模型就是不用。
>   加信息这条路对季数问题无效，加护栏才有意义——但见下。
> - **护栏的净增量约等于零**：25 条里 **19 条已被 2-3 硬规则（日期/platform）覆盖**（续作跟初代
>   往往差好几年，日期规则先命中）。独有的 6 条里 **3 条是误报**：
>   `亜人 第２部「衝突」→ 亜人 -衝突-`、`亜人 第3部「衝戟」→ 亜人 -衝戟-`、
>   `マルドゥック・スクランブル 第3部 排気 → …排気`——BGM 用副标题表达部数，主标题归一化后相同、
>   一侧无序号，正踩判据，而这三条日期完全一致、是**正确匹配**。剩下 3 条真错配里
>   `애슬론 또봇 2기` 是韩文，重跑时 2-1 语言护栏已经掐掉 LLM 分支，走不到这里。
>   净收益 ≈ 2 条，代价 ≈ 3 条误伤，负的。**别再提序号护栏。**
> - 连带否决原文的做法 2（序号当召回正向信号）和做法 4（撞车前置检查）：
>   撞车的发现由 5-1 质量检查的 `dup_in_season` / `dup_global` 承担，**事后视图 + 人工判定**，
>   不在写入路径上加判定逻辑。llm 撞车 21.4% 这个量级仍然存在，但它是审核工作量问题，不是代码问题。
> - **3-1 不做**：无候选的 pending 直接开 bgm.tv 网页手搜，不在审查界面里挂 `BgmSearch`。
>   注意 `web/src/components/BgmSearch.tsx` 与 `GET /api/bgm/search` 因此**保持死代码状态**，
>   要么择日删掉，要么留着——但别再当成待办。
> - **5-1 剩余（跨季度问题总览页）一并否决**：108 季本来就要逐季 review 一遍，
>   review 完问题自然收敛，总览页省下的是「找哪个季度有问题」，而逐季走一遍根本不需要找。
>   需要跨季清单时跑文首体检块的 SQL 即可。将来若逐季 review 完仍觉得缺，再当 P2 提。
>   §5 保留一节「现状」记录已完成的质量检查能力和「不要做 UNIQUE 约束」的结论。
>
> **2026-08-05（二）**：3-4 完成（`004_decision_reason.sql` + `ReasonPicker`），实现与原文大体一致，
> 但有两处偏离，都是动手后被数据推翻的：
> - **`reason` 没落 CHECK**。原文自己就写了「枚举是凭样例推的」，而 §7 清理很可能冒出新原因，
>   SQLite 改 CHECK 要重建 20616 行的 `season_items`。约束改放在 `schemas.py` 的 `ExcludeReason`
>   和 `web/src/lib/reasons.ts`——加一个取值改这两行，不用写迁移。落库前的校验（`other` 必须带 note、
>   `reason` 只能跟 `exclude` 一起来）在 `items.py` 的 `update_item` 里。
> - **`CHECK(action <> 'add' OR bgm_id IS NOT NULL)` 不能加，且以后也别加**。原文把它当成顺手补的
>   遗漏，实际上库里 11 条 `add` 有 **6 条 `bgm_id` 为空**，且每条都与一条 `skip` 严格配对
>   （mal 60629 / 61303 / 58888 / 58954 / 62494 / 63096）——那是「该挪进本季、bgm_id 待查」的待办，
>   正是 `target_season_id` 想表达的东西。加约束等于把这套用法判死刑，迁移当场就被这 6 行拒绝。
>   真正的毛病在 `process()` 的 add 分支拿 None 去 `get_subject()` 报了个看不懂的错，已改成
>   WARNING 跳过（`[override add] mal:x 缺 bgm_id`）。
> - 另外「移至其他季度」现在写**三条**记录：源季 `exclude/wrong_season`、源季 `overrides skip`
>   （带 `target_season_id`）、目标季 `overrides add`。原先只写后一条，源季看起来就是个普通 exclude，
>   配对关系丢了。`created_at` 靠 `ON CONFLICT DO UPDATE` 保护（原来的 `INSERT OR REPLACE`
>   是删+插，重复提交会把首次时间冲掉）。
> - 迁移过程中被 `uvicorn --reload` 摆了一道：改 `src/**.py` 会触发热重载，重载即调 `init_db()`，
>   跟手动跑的迁移撞车留下半应用状态。**下次写迁移前先停掉 dev server。**
>
> **2026-08-06**：2026-winter 整季打回重跑 + 人工审完，当作 §7 的单季试点。数据见 §7 的更新块。
> 三件与代码有关的事：
> - **`excluded/rule` 里混着人工判定**：全库 12 条 `media_type ∈ (tv/ona/movie/ova)` 却被记成
>   `excluded/rule`，其中 6 条是 2026 各季的语言护栏产物（合法），另外 6 条在 2025-fall
>   （62522 / 62676 / 62882 / 62900 / 63013 / 63277），是 `source='human'` 约定之前的遗留标注，
>   现行代码不可能产出。冬季的 63426「熊熊帮帮团4」原本也在这一类，重跑后已恢复成
>   `included/exact` bgm:639425（BGM 确实收录，2026-01-01 TV）——**这类行值得当成一个筛查维度**，
>   它们是「被误当成规则排除的漏收条目」。2025-fall 那 6 条留给该季重跑时处理。
> - **override 的「bgm_id 待查」待办要收尾**：winter/63096 的 `add` 缺 bgm_id，与 2025-fall 的
>   `skip/wrong_season` 配对。MAL 后来原生把它收进 winter 且 exact 匹配到 bgm:548189，
>   已给 override 补上 bgm_id（**不是删掉**——删了会破坏 004 定的三条配对记录）。
>   另外 5 条同类待办（60629 / 61303 / 58888 / 58954 / 62494）等对应季度重跑时同样处理。
> - **`run` 期间 dev server 可以不停**：只要不改 `src/**.py` 就不会触发热重载，WAL 下并发读写没冲突，
>   215 条全程零 `database is locked`。但 `get_connection()` 没设 `busy_timeout`（默认 0），
>   人工在 UI 上做写操作时仍可能撞上——脚本侧自己 `PRAGMA busy_timeout=30000` 兜一下。
>
> **主线依赖**：~~5-3 → 5-2 → 4-3 → 5-1 → 2-1 → 2-3 → 3-4~~（已完成）→ **§7 清理**。
> 2-3 提前做掉是因为它不改决策逻辑、只改输入质量，且 §7 重跑时要靠它提质。
> 止血环节到 2-3 为止，剩下的错配一律靠 §7 打回 + 人工审核吸收。

## P1 — 止血

**已全部完成**（最后一项 3-4 于 2026-08-05 落地）。下一步直接进 §7。

## 一次性清理

| 顺序 | 任务 | 成本 |
|---|---|---|
| 9 | **第 7 节** 99 个未跑过的季度整季打回 + 重跑（2026-winter 已作为试点跑完） | 机器时间为主，人工每季几分钟 |

## P2 — 规模化（批处理 100+ 季之前）

| 顺序 | 任务 | 成本 |
|---|---|---|
| 11 | **2-4** run 短路修复 + 并发 | 1 天 |
| 12 | **4-3** sync-bgm 并发 | 2h |
| 13 | **1-2** `is_new_anime` 过滤口径复查（等逐季 review 走完一遍后看漏了多少） | 待定 |
| 14 | **2-5 / 6** unknown media_type 源头拦截、END_YEAR、连接隔离、删死代码 | 半天 |
| 14.5 | **2-6** exact 分支也跑一遍 `match_conflicts()`（量级远小于 llm 侧） | 1h |
| 14.6 | **3-5** 让「模型判过但都不匹配」这个结论在 UI 上可见（和 2-4 A 一起做） | 2h |
| 15 | **`005_drop_items.sql`** 确认新 schema 稳定后删掉冻结的旧 `items` 表（004 已被 3-4 占用） | 10min |
