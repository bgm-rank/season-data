import { useState, useEffect } from 'react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { ItemEditModal } from '@/components/ItemEditModal'
import * as api from '@/services/api'
import type { Item, ItemStatus } from '@/types/api'

type StatusFilter = 'all' | 'pending' | 'included' | 'excluded'
type SourceFilter = 'all' | 'rule' | 'exact' | 'llm' | 'human'

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

// Returns true if bgm_air_date is clearly outside the season's expected range
function isDateOutOfRange(bgmAirDate: string, seasonId: string): boolean {
  const dateParts = bgmAirDate.split('-')
  if (dateParts.length < 2) return false
  const dateYear = parseInt(dateParts[0])
  const dateMonth = parseInt(dateParts[1])
  if (isNaN(dateYear) || isNaN(dateMonth)) return false

  const idParts = seasonId.split('-')
  if (idParts.length < 2) return false
  const seasonYear = parseInt(idParts[0])
  const seasonName = idParts[1]

  const RANGES: Record<string, [number, number]> = {
    winter: [1, 3],
    spring: [4, 6],
    summer: [7, 9],
    fall: [10, 12],
  }
  const range = RANGES[seasonName]
  if (!range) return false

  // Winter allows Dec of the previous year
  if (seasonName === 'winter' && dateYear === seasonYear - 1 && dateMonth === 12) return false

  if (dateYear !== seasonYear) return true
  // Allow 1-month buffer on each side for late-airing shows
  return dateMonth < range[0] - 1 || dateMonth > range[1] + 1
}

interface Props {
  seasonId: string
}

export function ItemList({ seasonId }: Props) {
  const [items, setItems] = useState<Item[]>([])
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingItem, setEditingItem] = useState<Item | null>(null)

  const loadItems = () => {
    setLoading(true)
    const params: { status?: string; source?: string } = {}
    if (filter !== 'all') params.status = filter
    if (sourceFilter !== 'all') params.source = sourceFilter
    api.getItems(seasonId, Object.keys(params).length ? params : undefined)
      .then(setItems)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadItems()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seasonId, filter, sourceFilter])

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

  const btnClass = (active: boolean) =>
    `px-3 py-1 rounded text-sm transition-colors ${
      active
        ? 'bg-primary text-primary-foreground'
        : 'bg-muted text-muted-foreground hover:bg-muted/80'
    }`

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">全番组列表</h2>

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
      </div>

      {error && <div className="text-sm text-destructive">{error}</div>}

      {loading ? (
        <div className="text-sm text-muted-foreground">加载中...</div>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="py-6 text-center text-sm text-muted-foreground">
            暂无条目
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <Card
              key={item.mal_id}
              className={`${
                item.status !== 'pending'
                  ? 'cursor-pointer hover:bg-muted/50 transition-colors'
                  : ''
              }`}
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
                            isDateOutOfRange(item.bgm_air_date, item.season_id)
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
                </div>
                <div className="flex items-center gap-2 shrink-0">
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
          onUpdated={() => {
            setEditingItem(null)
            loadItems()
          }}
        />
      )}
    </div>
  )
}
