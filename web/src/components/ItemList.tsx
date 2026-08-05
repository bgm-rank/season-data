import { useState, useEffect, useRef } from 'react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { ItemEditModal } from '@/components/ItemEditModal'
import { emitItemsChanged, onItemsChanged } from '@/lib/itemEvents'
import { reasonLabel } from '@/lib/reasons'
import * as api from '@/services/api'
import type { Item, ItemStatus, IssueKind } from '@/types/api'

type StatusFilter = 'all' | 'pending' | 'included' | 'excluded'
type SourceFilter = 'all' | 'rule' | 'exact' | 'llm' | 'human'
type IssueFilter = 'all' | IssueKind

// 一次拉全季。最大的季度 339 条，后端上限 2000，分页在这个规模上纯属负担
const PAGE_LIMIT = 1000

const STATUS_LABELS: Record<ItemStatus, string> = {
  pending: '待审核',
  included: '已收录',
  excluded: '已排除',
}

const STATUS_VARIANTS: Record<ItemStatus, 'default' | 'secondary' | 'outline'> = {
  pending: 'outline',
  included: 'default',
  excluded: 'secondary',
}

const SOURCE_LABELS: Record<string, string> = {
  rule: '规则排除',
  exact: '精确匹配',
  llm: 'LLM',
  human: '人工',
}

const ISSUE_LABELS: Record<IssueKind, string> = {
  dup_in_season: '季内重复',
  dup_global: '跨季重复',
  date_mismatch: '日期不符',
  no_bgm_name: '无 BGM 名',
}

interface Props {
  seasonId: string
}

export function ItemList({ seasonId }: Props) {
  const [items, setItems] = useState<Item[]>([])
  const [total, setTotal] = useState(0)
  const [issueCounts, setIssueCounts] = useState<Partial<Record<IssueKind, number>>>({})
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [issueFilter, setIssueFilter] = useState<IssueFilter>('all')
  // 首次加载才允许卸载列表；后续刷新只置灰，否则 DOM 重建会把滚动位置清零
  const [initialLoading, setInitialLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rowErrors, setRowErrors] = useState<Record<number, string>>({})
  const [editingItem, setEditingItem] = useState<Item | null>(null)
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set())
  const [dirtyCount, setDirtyCount] = useState(0)
  const [stale, setStale] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const cardRefs = useRef<Map<number, HTMLDivElement>>(new Map())

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
   * 这里的行内 ✗ 和快捷键 x 刻意不带排除原因：批量清理时要的就是零成本，
   * 所以服务端把 reason/note 写成 NULL。要记原因走审核队列或编辑弹窗。
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

  const quickPatch = async (item: Item, action: 'exclude' | 'pending', e?: React.MouseEvent) => {
    e?.stopPropagation()
    if (busyIds.has(item.mal_id)) return
    const snapshot = item
    setRowError(item.mal_id, null)
    applyUpdate(optimisticOf(item, action))
    setBusy(item.mal_id, true)
    try {
      applyUpdate(await api.patchItem(seasonId, item.mal_id, { action }))
      setDirtyCount((n) => n + 1)
      emitItemsChanged('ItemList')
    } catch (err) {
      applyUpdate(snapshot)
      setRowError(item.mal_id, err instanceof Error ? err.message : '操作失败，已回滚')
    } finally {
      setBusy(item.mal_id, false)
    }
  }

  const syncItem = async (malId: number, e: React.MouseEvent) => {
    e.stopPropagation()
    setRowError(malId, null)
    setBusy(malId, true)
    try {
      applyUpdate(await api.syncBgmItem(seasonId, malId))
    } catch (err) {
      setRowError(malId, err instanceof Error ? err.message : '刷新失败')
    } finally {
      setBusy(malId, false)
    }
  }

  const loadItems = () => {
    setRefreshing(true)
    setError(null)
    const params: { status?: string; source?: string; issue?: string; limit: number } = {
      limit: PAGE_LIMIT,
    }
    if (filter !== 'all') params.status = filter
    if (sourceFilter !== 'all') params.source = sourceFilter
    if (issueFilter !== 'all') params.issue = issueFilter
    api
      .getItems(seasonId, params)
      .then((res) => {
        setItems(res.items)
        setTotal(res.total)
        setIssueCounts(res.issue_counts)
        setDirtyCount(0)
        setStale(false)
        setSelectedIndex(-1)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        setRefreshing(false)
        setInitialLoading(false)
      })
  }

  useEffect(() => {
    loadItems()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seasonId, filter, sourceFilter, issueFilter])

  // ReviewQueue 同页处理条目后本列表就过期了。只提示不自动重载，
  // 免得把用户正在看的位置冲掉。
  useEffect(() => onItemsChanged('ItemList', () => setStale(true)), [])

  // 键盘导航绑在容器上而不是 window：ReviewQueue 同页挂载且已占用了全局的
  // x / s / 1-9 / Enter，绑 window 会一次按键同时改两个组件的条目
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (editingItem) return
    const target = e.target as HTMLElement
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return
    if (!items.length) return

    const move = (delta: number) => {
      e.preventDefault()
      const next = Math.max(0, Math.min(items.length - 1, selectedIndex + delta))
      setSelectedIndex(next)
      cardRefs.current.get(items[next].mal_id)?.scrollIntoView({ block: 'nearest' })
    }

    if (e.key === 'j') return move(selectedIndex < 0 ? 0 : 1)
    if (e.key === 'k') return move(selectedIndex < 0 ? 0 : -1)

    const current = selectedIndex >= 0 ? items[selectedIndex] : null
    if (!current) return
    if (e.key === 'x' && current.status !== 'excluded') {
      e.preventDefault()
      void quickPatch(current, 'exclude')
    } else if (e.key === 'r' && current.status !== 'pending') {
      e.preventDefault()
      void quickPatch(current, 'pending')
    } else if (e.key === 'Enter' && current.status !== 'pending') {
      e.preventDefault()
      setEditingItem(current)
    }
  }

  const statusTabs: { value: StatusFilter; label: string }[] = [
    { value: 'all', label: '全部' },
    { value: 'pending', label: '待审核' },
    { value: 'included', label: '已收录' },
    { value: 'excluded', label: '已排除' },
  ]

  const sourceTabs: { value: SourceFilter; label: string }[] = [
    { value: 'all', label: '全部来源' },
    { value: 'rule', label: '规则' },
    { value: 'exact', label: '精确匹配' },
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
    `px-3 py-1 rounded text-sm transition-colors ${
      active
        ? 'bg-primary text-primary-foreground'
        : muted
          ? 'bg-muted/50 text-muted-foreground/40'
          : 'bg-muted text-muted-foreground hover:bg-muted/80'
    }`

  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-3">
        <h2 className="text-lg font-semibold">全番组列表</h2>
        {!initialLoading && <span className="text-sm text-muted-foreground">共 {total} 条</span>}
        {(dirtyCount > 0 || stale) && (
          <span className="text-sm text-muted-foreground">
            {stale ? '审核队列有改动' : `本次已修改 ${dirtyCount} 条`}
            {' · '}
            <button onClick={loadItems} className="underline hover:text-foreground">
              刷新
            </button>
          </span>
        )}
      </div>

      <div className="space-y-2">
        <div className="flex gap-2 flex-wrap">
          {statusTabs.map((t) => (
            <button key={t.value} onClick={() => setFilter(t.value)} className={btnClass(filter === t.value)}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex gap-2 flex-wrap">
          {sourceTabs.map((t) => (
            <button key={t.value} onClick={() => setSourceFilter(t.value)} className={btnClass(sourceFilter === t.value)}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex gap-2 flex-wrap">
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

      {error && <div className="text-sm text-destructive">{error}</div>}

      {initialLoading ? (
        <div className="text-sm text-muted-foreground">加载中...</div>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="py-6 text-center text-sm text-muted-foreground">
            暂无条目
          </CardContent>
        </Card>
      ) : (
        <div
          tabIndex={0}
          onKeyDown={handleKeyDown}
          data-keyscope="item-list"
          className={`space-y-2 outline-none ${refreshing ? 'opacity-60 pointer-events-none' : ''}`}
        >
          {items.map((item, idx) => (
            <Card
              key={item.mal_id}
              ref={(el: HTMLDivElement | null) => {
                if (el) cardRefs.current.set(item.mal_id, el)
                else cardRefs.current.delete(item.mal_id)
              }}
              className={`${
                item.status !== 'pending'
                  ? 'cursor-pointer hover:bg-muted/50 transition-colors'
                  : ''
              } ${idx === selectedIndex ? 'ring-2 ring-primary' : ''}`}
              onClick={() => item.status !== 'pending' && setEditingItem(item)}
            >
              <CardContent className="py-3 px-4 flex items-center justify-between gap-3">
                <div className="flex-1 min-w-0 space-y-0.5">
                  {/* MAL section */}
                  <div className="flex text-xs">
                    <span className="w-8 shrink-0 text-muted-foreground/50">MAL</span>
                    <a
                      href={`https://myanimelist.net/anime/${item.mal_id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-blue-500 underline hover:text-blue-600"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {item.mal_id}
                    </a>
                    <span className="ml-2 text-muted-foreground/60">{item.mal_media_type}</span>
                    {item.mal_rating !== 'general' && (
                      <span className="ml-1 text-muted-foreground/60">· {item.mal_rating}</span>
                    )}
                  </div>
                  <div className="flex text-xs text-muted-foreground">
                    <span className="w-8 shrink-0" />
                    <span className="truncate">{item.mal_title}</span>
                  </div>
                  {item.mal_title_ja && (
                    <div className="flex text-xs">
                      <span className="w-8 shrink-0" />
                      <span className="truncate font-medium text-foreground">{item.mal_title_ja}</span>
                    </div>
                  )}

                  {/* BGM section */}
                  {item.bgm_id && (
                    <>
                      <div className="flex text-xs">
                        <span className="w-8 shrink-0 text-muted-foreground/50">BGM</span>
                        <span className="truncate font-medium text-foreground">{item.bgm_name ?? '—'}</span>
                      </div>
                      {item.bgm_name_cn && (
                        <div className="flex text-xs text-muted-foreground">
                          <span className="w-8 shrink-0" />
                          <span className="truncate">{item.bgm_name_cn}</span>
                        </div>
                      )}
                      <div className="flex text-xs">
                        <span className="w-8 shrink-0" />
                        <a
                          href={`https://bgm.tv/subject/${item.bgm_id}`}
                          target="_blank"
                          rel="noreferrer"
                          className="text-blue-500 underline hover:text-blue-600"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {item.bgm_id}
                        </a>
                      </div>
                      {item.bgm_air_date && (
                        <div className="flex text-xs">
                          <span className="w-8 shrink-0" />
                          <span className={
                            item.issues.includes('date_mismatch')
                              ? 'text-destructive font-semibold'
                              : 'text-muted-foreground'
                          }>
                            {item.bgm_air_date.slice(0, 7)}
                          </span>
                        </div>
                      )}
                      {item.source === 'llm' && item.confidence != null && (
                        <div className="flex text-xs text-muted-foreground">
                          <span className="w-8 shrink-0" />
                          <span>{Math.round(item.confidence * 100)}%</span>
                        </div>
                      )}
                    </>
                  )}

                  {rowErrors[item.mal_id] && (
                    <div className="flex text-xs">
                      <span className="w-8 shrink-0" />
                      <span className="text-destructive">{rowErrors[item.mal_id]}</span>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {item.issues.map((k) => (
                    <Badge key={k} variant="destructive" className="text-xs">
                      ⚠{ISSUE_LABELS[k]}
                    </Badge>
                  ))}
                  {item.bgm_id && (
                    <button
                      onClick={(e) => void syncItem(item.mal_id, e)}
                      disabled={busyIds.has(item.mal_id)}
                      className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
                      title="强制刷新 BGM 数据"
                    >
                      ↻
                    </button>
                  )}
                  {item.status !== 'excluded' && (
                    <button
                      onClick={(e) => void quickPatch(item, 'exclude', e)}
                      disabled={busyIds.has(item.mal_id)}
                      className="text-xs text-muted-foreground hover:text-destructive disabled:opacity-40"
                      title="排除（快捷键 x）"
                    >
                      ✗
                    </button>
                  )}
                  {item.status !== 'pending' && (
                    <button
                      onClick={(e) => void quickPatch(item, 'pending', e)}
                      disabled={busyIds.has(item.mal_id)}
                      className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
                      title="打回待审核（快捷键 r）"
                    >
                      ↺
                    </button>
                  )}
                  {item.reason && (
                    <Badge variant="secondary" className="text-xs" title={item.note ?? undefined}>
                      {reasonLabel(item.reason)}
                      {item.note && ' *'}
                    </Badge>
                  )}
                  {item.source && (
                    <Badge variant="outline" className="text-xs">
                      {SOURCE_LABELS[item.source] ?? item.source}
                    </Badge>
                  )}
                  <Badge variant={STATUS_VARIANTS[item.status]}>
                    {STATUS_LABELS[item.status]}
                  </Badge>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {editingItem && (
        <ItemEditModal
          item={editingItem}
          seasonId={seasonId}
          onClose={() => setEditingItem(null)}
          onUpdated={(updated) => {
            setEditingItem(null)
            applyUpdate(updated)
            setDirtyCount((n) => n + 1)
            emitItemsChanged('ItemList')
          }}
        />
      )}
    </div>
  )
}
