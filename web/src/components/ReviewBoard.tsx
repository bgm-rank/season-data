import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ItemDetail } from '@/components/ItemDetail'
import { ISSUE_LABELS, ItemRow, type BoardRow } from '@/components/ItemRow'
import { onItemsChanged } from '@/lib/itemEvents'
import * as api from '@/services/api'
import type {
  ExcludeReason,
  IssueKind,
  Item,
  ItemDetail as Detail,
  Override,
  SeasonSummary,
} from '@/types/api'

type StatusFilter = 'all' | 'pending' | 'included' | 'excluded'
type SourceFilter = 'all' | 'rule' | 'exact' | 'llm' | 'human'
type IssueFilter = 'all' | IssueKind

// 一次拉全季。最大的季度 339 条，后端上限 2000，分页在这个规模上纯属负担
const PAGE_LIMIT = 1000

interface Props {
  seasonId: string
}

/**
 * 审核台：左列全季条目（恒按 mal_id 升序），右列选中条目的完整详情 + 操作。
 *
 * 这一个 island 取代了原来的 ItemList + ReviewQueue + OverrideManager 三件套。
 * 拆成三个组件时它们是各自独立的 Astro island、React state 不共享，同一条番在两处
 * 显示且状态不同步，两套键盘快捷键还得靠 [data-keyscope] 互相躲闪。合成一个之后
 * 只有一份 items、一个键盘 scope。
 */
export function ReviewBoard({ seasonId }: Props) {
  const [items, setItems] = useState<Item[]>([])
  const [orphans, setOrphans] = useState<Override[]>([])
  const [total, setTotal] = useState(0)
  const [issueCounts, setIssueCounts] = useState<Partial<Record<IssueKind, number>>>({})
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [issueFilter, setIssueFilter] = useState<IssueFilter>('all')

  // 首次加载才允许卸载列表；后续刷新只置灰，否则 DOM 重建会把滚动位置清零
  const [initialLoading, setInitialLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const [rowErrors, setRowErrors] = useState<Record<number, string>>({})
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set())
  const [stale, setStale] = useState(false)

  const [selectedMalId, setSelectedMalId] = useState<number | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [selectedCandidate, setSelectedCandidate] = useState<number | null>(null)
  const [seasons, setSeasons] = useState<SeasonSummary[]>([])

  const [addOpen, setAddOpen] = useState(false)
  const [addMalId, setAddMalId] = useState('')
  const [addBgmId, setAddBgmId] = useState('')

  const rowRefs = useRef<Map<number, HTMLDivElement>>(new Map())
  const listRef = useRef<HTMLDivElement>(null)
  // j/k 连按会连发详情请求，回来的顺序不保证。只认最后一次的序号，其余丢弃
  const detailSeq = useRef(0)

  // ── 数据加载 ─────────────────────────────────────────────────────────────

  const loadList = useCallback(() => {
    setRefreshing(true)
    setListError(null)
    const params: { status?: string; source?: string; issue?: string; limit: number } = { limit: PAGE_LIMIT }
    if (filter !== 'all') params.status = filter
    if (sourceFilter !== 'all') params.source = sourceFilter
    if (issueFilter !== 'all') params.issue = issueFilter

    Promise.all([api.getItems(seasonId, params), api.getOverrides(seasonId)])
      .then(([res, ovs]) => {
        setItems(res.items) // 后端恒 mal_id ASC，这里不再排序
        setTotal(res.total)
        setIssueCounts(res.issue_counts)
        setOrphans(ovs.filter((o) => !o.in_season_items))
        setStale(false)
      })
      .catch((e: unknown) => setListError(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        setRefreshing(false)
        setInitialLoading(false)
      })
  }, [seasonId, filter, sourceFilter, issueFilter])

  useEffect(() => loadList(), [loadList])

  useEffect(() => {
    api.getSeasons().then(setSeasons).catch(() => {})
  }, [])

  // SeasonActions 是另一个 island，跑完 run / sync-bgm 后本列表就过期了。
  // 只提示不自动重载——重载会把正在审核的位置冲掉。
  useEffect(() => onItemsChanged('ReviewBoard', () => setStale(true)), [])

  // ── 左列行（条目 + 孤儿 override，按 mal_id 归并）─────────────────────────

  const rows = useMemo<BoardRow[]>(() => {
    const itemRows: BoardRow[] = items.map((it) => ({ kind: 'item', malId: it.mal_id, item: it }))
    // 孤儿 override 不受状态/来源/问题筛选影响——它们还没有状态可筛。
    // 只在「全部」下混进来，免得筛选结果里冒出对不上条件的行。
    const showOrphans = filter === 'all' && sourceFilter === 'all' && issueFilter === 'all'
    if (!showOrphans) return itemRows
    const merged: BoardRow[] = [
      ...itemRows,
      ...orphans.map((o): BoardRow => ({ kind: 'orphan', malId: o.mal_id, override: o })),
    ]
    return merged.sort((a, b) => a.malId - b.malId)
  }, [items, orphans, filter, sourceFilter, issueFilter])

  const selectedRow = rows.find((r) => r.malId === selectedMalId) ?? null
  const selectedOrphan = selectedRow?.kind === 'orphan' ? selectedRow.override : null

  // 筛选变化后选中项可能已经不在列表里了，清掉，免得右侧显示一条左边看不见的番
  useEffect(() => {
    if (selectedMalId != null && !rows.some((r) => r.malId === selectedMalId)) {
      setSelectedMalId(null)
    }
  }, [rows, selectedMalId])

  // ── 详情 ─────────────────────────────────────────────────────────────────

  const loadDetail = useCallback(
    (malId: number) => {
      const seq = ++detailSeq.current
      setDetailLoading(true)
      setDetailError(null)
      api
        .getItemDetail(seasonId, malId)
        .then((d) => {
          if (seq !== detailSeq.current) return
          setDetail(d)
        })
        .catch((e: unknown) => {
          if (seq !== detailSeq.current) return
          setDetail(null)
          setDetailError(e instanceof Error ? e.message : String(e))
        })
        .finally(() => {
          if (seq === detailSeq.current) setDetailLoading(false)
        })
    },
    [seasonId]
  )

  useEffect(() => {
    setSelectedCandidate(null)
    if (selectedMalId == null || selectedRow?.kind === 'orphan') {
      detailSeq.current++ // 让在途的请求作废
      setDetail(null)
      setDetailError(null)
      setDetailLoading(false)
      return
    }
    loadDetail(selectedMalId)
  }, [selectedMalId, selectedRow?.kind, loadDetail])

  // ── 写操作 ───────────────────────────────────────────────────────────────

  const setBusy = (malId: number, busy: boolean) =>
    setBusyIds((s) => {
      const n = new Set(s)
      if (busy) n.add(malId)
      else n.delete(malId)
      return n
    })

  const setRowError = (malId: number, msg: string | null) =>
    setRowErrors((prev) => {
      const n = { ...prev }
      if (msg) n[malId] = msg
      else delete n[malId]
      return n
    })

  const applyUpdate = (updated: Item) =>
    setItems((prev) => prev.map((it) => (it.mal_id === updated.mal_id ? updated : it)))

  /**
   * 服务端 PATCH 后条目会变成什么样（见 src/api/routers/items.py 的 update_item）。
   *
   * 行内 ✗ 和快捷键 x 刻意不带排除原因：批量清理时要的就是零成本，所以服务端把
   * reason/note 写成 NULL。要记原因走右侧面板的原因选择器。
   */
  const optimisticOf = (item: Item, action: 'exclude' | 'pending'): Item =>
    action === 'exclude'
      ? { ...item, status: 'excluded', source: 'human', reason: null, note: null } // 排除保留 bgm_id
      : {
          ...item,
          status: 'pending',
          source: null,
          bgm_id: null,
          bgm_name: null,
          bgm_name_cn: null,
          bgm_air_date: null,
          confidence: null,
          candidates: null,
          error: null,
          reason: null,
          note: null,
          issues: [],
        }

  /** 所有单条写操作的公共外壳：置忙 → 调 API → 更新左列行 → 重拉详情 → 出错回滚。 */
  const mutate = useCallback(
    async (malId: number, call: () => Promise<Item | void>, optimistic?: Item) => {
      if (busyIds.has(malId)) return
      const snapshot = items.find((it) => it.mal_id === malId) ?? null
      setRowError(malId, null)
      setDetailError(null)
      if (optimistic) applyUpdate(optimistic)
      setBusy(malId, true)
      try {
        const updated = await call()
        if (updated) applyUpdate(updated)
        // 列表行拿到了新值，但详情的富字段（BGM 简介/标签等）得重拉才对得上
        if (selectedMalId === malId) loadDetail(malId)
      } catch (err) {
        if (snapshot) applyUpdate(snapshot)
        const msg = err instanceof Error ? err.message : '操作失败，已回滚'
        setRowError(malId, msg)
        setDetailError(msg)
      } finally {
        setBusy(malId, false)
      }
    },
    [busyIds, items, selectedMalId, loadDetail]
  )

  const quickPatch = useCallback(
    (item: Item, action: 'exclude' | 'pending') =>
      mutate(item.mal_id, () => api.patchItem(seasonId, item.mal_id, { action }), optimisticOf(item, action)),
    [mutate, seasonId]
  )

  const syncItem = useCallback(
    (malId: number) => mutate(malId, () => api.syncBgmItem(seasonId, malId)),
    [mutate, seasonId]
  )

  const includeItem = useCallback(
    (bgmId: number) => {
      if (selectedMalId == null) return
      void mutate(selectedMalId, () =>
        api.patchItem(seasonId, selectedMalId, { action: 'include', bgm_id: bgmId })
      )
    },
    [mutate, seasonId, selectedMalId]
  )

  const excludeItem = useCallback(
    (reason: ExcludeReason | null, note: string | null) => {
      if (selectedMalId == null) return
      void mutate(selectedMalId, () =>
        api.patchItem(seasonId, selectedMalId, { action: 'exclude', reason, note })
      )
    },
    [mutate, seasonId, selectedMalId]
  )

  const pendingItem = useCallback(() => {
    if (selectedMalId == null) return
    const item = items.find((it) => it.mal_id === selectedMalId)
    void mutate(
      selectedMalId,
      () => api.patchItem(seasonId, selectedMalId, { action: 'pending' }),
      item ? optimisticOf(item, 'pending') : undefined
    )
  }, [mutate, seasonId, selectedMalId, items])

  const moveToSeason = useCallback(
    (targetSeasonId: string, bgmId: number) => {
      if (selectedMalId == null) return
      void mutate(selectedMalId, async () => {
        // 三条记录缺一不可：源季的决策、源季的意图、目标季的意图。
        // 只写目标季的 add 会让源季看起来像个普通的 exclude，配对关系就丢了。
        const updated = await api.patchItem(seasonId, selectedMalId, {
          action: 'exclude',
          reason: 'wrong_season',
        })
        await api.createOverride(seasonId, {
          mal_id: selectedMalId,
          action: 'skip',
          reason: 'wrong_season',
          target_season_id: targetSeasonId,
        })
        await api.createOverride(targetSeasonId, { mal_id: selectedMalId, action: 'add', bgm_id: bgmId })
        return updated
      })
    },
    [mutate, seasonId, selectedMalId]
  )

  const deleteOverride = useCallback(
    async (malId: number) => {
      setBusy(malId, true)
      try {
        await api.deleteOverride(seasonId, malId)
        setOrphans((prev) => prev.filter((o) => o.mal_id !== malId))
        if (selectedMalId === malId) {
          // 孤儿删掉后这一行就没了；已落库的条目还在，重拉详情把 override 段抹掉
          if (selectedOrphan) setSelectedMalId(null)
          else loadDetail(malId)
        }
      } catch (e) {
        setDetailError(e instanceof Error ? e.message : '删除失败')
      } finally {
        setBusy(malId, false)
      }
    },
    [seasonId, selectedMalId, selectedOrphan, loadDetail]
  )

  const createAddOverride = useCallback(async () => {
    const malId = parseInt(addMalId.trim(), 10)
    const bgmId = parseInt(addBgmId.trim(), 10)
    if (!malId || malId <= 0 || !bgmId || bgmId <= 0) return
    try {
      await api.createOverride(seasonId, { mal_id: malId, action: 'add', bgm_id: bgmId })
      setAddOpen(false)
      setAddMalId('')
      setAddBgmId('')
      loadList()
    } catch (e) {
      setListError(e instanceof Error ? e.message : '创建失败')
    }
  }, [seasonId, addMalId, addBgmId, loadList])

  // ── 键盘 ─────────────────────────────────────────────────────────────────

  const selectedIndex = rows.findIndex((r) => r.malId === selectedMalId)

  const handleKeyDown = (e: React.KeyboardEvent) => {
    const target = e.target as HTMLElement
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') return
    if (!rows.length) return

    const move = (delta: number) => {
      e.preventDefault()
      const next = selectedIndex < 0 ? 0 : Math.max(0, Math.min(rows.length - 1, selectedIndex + delta))
      setSelectedMalId(rows[next].malId)
      rowRefs.current.get(rows[next].malId)?.scrollIntoView({ block: 'nearest' })
    }

    if (e.key === 'j' || e.key === 'ArrowDown') return move(selectedIndex < 0 ? 0 : 1)
    if (e.key === 'k' || e.key === 'ArrowUp') return move(selectedIndex < 0 ? 0 : -1)

    const current = selectedRow?.kind === 'item' ? selectedRow.item : null
    if (!current) return

    if (/^[1-9]$/.test(e.key)) {
      const i = parseInt(e.key, 10) - 1
      if (detail?.candidates?.[i]) {
        e.preventDefault()
        setSelectedCandidate(i)
      }
    } else if (e.key === 'x' && current.status !== 'excluded') {
      e.preventDefault()
      void quickPatch(current, 'exclude')
    } else if (e.key === 'r' && current.status !== 'pending') {
      e.preventDefault()
      pendingItem()
    } else if (e.key === 'Enter' && selectedCandidate != null && detail?.candidates?.[selectedCandidate]) {
      e.preventDefault()
      includeItem(detail.candidates[selectedCandidate].bgm_id)
    }
  }

  // ── 渲染 ─────────────────────────────────────────────────────────────────

  const statusTabs: { value: StatusFilter; label: string }[] = [
    { value: 'all', label: '全部' },
    { value: 'pending', label: '待审核' },
    { value: 'included', label: '已收录' },
    { value: 'excluded', label: '已排除' },
  ]

  const sourceTabs: { value: SourceFilter; label: string }[] = [
    { value: 'all', label: '全部来源' },
    { value: 'rule', label: '规则' },
    { value: 'exact', label: '精确' },
    { value: 'llm', label: 'LLM' },
    { value: 'human', label: '人工' },
  ]

  const issueTabs: { value: IssueFilter; label: string }[] = [
    { value: 'all', label: '不筛问题' },
    ...(Object.keys(ISSUE_LABELS) as IssueKind[]).map((k) => ({
      value: k as IssueFilter,
      label: `⚠${ISSUE_LABELS[k]} ${issueCounts[k] ?? 0}`,
    })),
  ]

  const btnClass = (active: boolean, muted = false) =>
    `px-2 py-0.5 rounded text-xs transition-colors ${
      active
        ? 'bg-primary text-primary-foreground'
        : muted
          ? 'bg-muted/50 text-muted-foreground/40'
          : 'bg-muted text-muted-foreground hover:bg-muted/80'
    }`

  return (
    <div className="flex min-h-0 flex-1" onKeyDown={handleKeyDown} tabIndex={-1}>
      {/* ── 左列 ─────────────────────────────────────────────────────── */}
      <div
        ref={listRef}
        className="flex w-[24rem] shrink-0 flex-col border-r outline-none"
        tabIndex={0}
        role="listbox"
        aria-label="全番组列表"
      >
        <div className="space-y-1.5 border-b px-2 py-2">
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-semibold">全番组列表</span>
            {!initialLoading && (
              <span className="text-xs text-muted-foreground">
                {total} 条{orphans.length > 0 && ` · ${orphans.length} 待 run`}
              </span>
            )}
            <button
              onClick={() => setAddOpen((o) => !o)}
              className="ml-auto text-xs text-muted-foreground hover:text-foreground"
              title="MAL 漏抓的番，手动加一条 override"
            >
              + 添加
            </button>
            {stale && (
              <button onClick={loadList} className="text-xs text-muted-foreground underline hover:text-foreground">
                有改动 · 刷新
              </button>
            )}
          </div>

          {addOpen && (
            <div className="flex flex-wrap items-center gap-1.5 rounded border bg-muted/30 p-2">
              <Input
                type="number"
                placeholder="mal_id"
                value={addMalId}
                onChange={(e) => setAddMalId(e.target.value)}
                className="h-7 w-24 text-xs"
              />
              <Input
                type="number"
                placeholder="bgm_id"
                value={addBgmId}
                onChange={(e) => setAddBgmId(e.target.value)}
                className="h-7 w-24 text-xs"
              />
              <Button size="xs" onClick={() => void createAddOverride()}>
                添加
              </Button>
              <p className="w-full text-[10px] text-muted-foreground">运行匹配后才会作为条目出现</p>
            </div>
          )}

          <div className="flex flex-wrap gap-1">
            {statusTabs.map((t) => (
              <button key={t.value} onClick={() => setFilter(t.value)} className={btnClass(filter === t.value)}>
                {t.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-1">
            {sourceTabs.map((t) => (
              <button
                key={t.value}
                onClick={() => setSourceFilter(t.value)}
                className={btnClass(sourceFilter === t.value)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-1">
            {issueTabs.map((t) => {
              const empty = t.value !== 'all' && !issueCounts[t.value as IssueKind]
              return (
                <button
                  key={t.value}
                  onClick={() => setIssueFilter(t.value)}
                  disabled={empty}
                  className={btnClass(issueFilter === t.value, empty)}
                >
                  {t.label}
                </button>
              )
            })}
          </div>
        </div>

        {listError && <div className="px-2 py-1 text-xs text-destructive">{listError}</div>}

        <div className={`flex-1 overflow-y-auto p-1 ${refreshing ? 'opacity-60' : ''}`}>
          {initialLoading ? (
            <div className="p-3 text-xs text-muted-foreground">加载中...</div>
          ) : rows.length === 0 ? (
            <div className="p-3 text-xs text-muted-foreground">暂无条目</div>
          ) : (
            rows.map((row) => (
              <div
                key={row.malId}
                ref={(el: HTMLDivElement | null) => {
                  if (el) rowRefs.current.set(row.malId, el)
                  else rowRefs.current.delete(row.malId)
                }}
              >
                <ItemRow
                  row={row}
                  selected={row.malId === selectedMalId}
                  busy={busyIds.has(row.malId)}
                  error={rowErrors[row.malId] ?? null}
                  onSelect={() => {
                    setSelectedMalId(row.malId)
                    // 点行之后焦点得留在列表上，否则接着按 j/k/x 什么都不会发生
                    listRef.current?.focus()
                  }}
                  onExclude={() => row.kind === 'item' && void quickPatch(row.item, 'exclude')}
                  onPending={() => row.kind === 'item' && void quickPatch(row.item, 'pending')}
                  onSync={() => void syncItem(row.malId)}
                />
              </div>
            ))
          )}
        </div>

        <div className="border-t px-2 py-1 text-[10px] text-muted-foreground">
          j/k 上下 · 1-9 选候选 · Enter 收录 · x 排除 · r 打回
        </div>
      </div>

      {/* ── 右列 ─────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto">
        {selectedMalId == null ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
            <span>从左边选一条番组</span>
            <Badge variant="outline">j / k 也能移动</Badge>
          </div>
        ) : (
          <ItemDetail
            detail={detail}
            orphan={selectedOrphan}
            loading={detailLoading}
            error={detailError}
            busy={busyIds.has(selectedMalId)}
            seasons={seasons}
            seasonId={seasonId}
            selectedCandidate={selectedCandidate}
            onSelectCandidate={setSelectedCandidate}
            onInclude={includeItem}
            onExclude={excludeItem}
            onPending={pendingItem}
            onSync={() => void syncItem(selectedMalId)}
            onMove={moveToSeason}
            onDeleteOverride={(malId) => void deleteOverride(malId)}
          />
        )}
      </div>
    </div>
  )
}
