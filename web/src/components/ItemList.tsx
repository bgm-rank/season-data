import { useState, useEffect } from 'react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { ItemEditModal } from '@/components/ItemEditModal'
import * as api from '@/services/api'
import type { Item, ItemStatus } from '@/types/api'

type StatusFilter = 'all' | 'pending' | 'included' | 'excluded'

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

interface Props {
  seasonId: string
}

export function ItemList({ seasonId }: Props) {
  const [items, setItems] = useState<Item[]>([])
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingItem, setEditingItem] = useState<Item | null>(null)

  const loadItems = () => {
    setLoading(true)
    const params = filter !== 'all' ? { status: filter } : undefined
    api.getItems(seasonId, params)
      .then(setItems)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadItems()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seasonId, filter])

  const tabs: { value: StatusFilter; label: string }[] = [
    { value: 'all', label: '全部' },
    { value: 'pending', label: '待审核' },
    { value: 'included', label: '已收录' },
    { value: 'excluded', label: '已排除' },
  ]

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">全番组列表</h2>

      <div className="flex gap-2 flex-wrap">
        {tabs.map((t) => (
          <button
            key={t.value}
            onClick={() => setFilter(t.value)}
            className={`px-3 py-1 rounded text-sm transition-colors ${
              filter === t.value
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-muted/80'
            }`}
          >
            {t.label}
          </button>
        ))}
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
                <div className="flex-1 min-w-0">
                  <span className="font-medium text-sm truncate block">{item.mal_title}</span>
                  {item.bgm_id && (
                    <span className="text-xs text-muted-foreground">bgm:{item.bgm_id}</span>
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
