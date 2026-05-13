import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import * as api from '@/services/api'
import type { Item } from '@/types/api'

const SOURCE_LABELS: Record<string, string> = {
  rule: '规则排除',
  exact: '精确匹配',
  llm: 'LLM',
  human: '人工',
}

const STATUS_LABELS: Record<string, string> = {
  pending: '待审核',
  included: '已收录',
  excluded: '已排除',
}

interface Props {
  item: Item
  seasonId: string
  onClose: () => void
  onUpdated: () => void
}

export function ItemEditModal({ item, seasonId, onClose, onUpdated }: Props) {
  const [action, setAction] = useState<'include' | 'exclude' | 'pending'>('include')
  const [bgmId, setBgmId] = useState(item.bgm_id != null ? String(item.bgm_id) : '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    setLoading(true)
    setError(null)
    try {
      const body =
        action === 'include'
          ? { action: 'include' as const, bgm_id: parseInt(bgmId) }
          : action === 'pending'
            ? { action: 'pending' as const }
            : { action: 'exclude' as const }
      await api.patchItem(seasonId, item.mal_id, body)
      onUpdated()
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="text-base">{item.mal_title}</DialogTitle>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div className="flex gap-2 flex-wrap text-sm">
            <Badge variant="outline">{item.mal_media_type}</Badge>
            {item.source && (
              <Badge variant="secondary">{SOURCE_LABELS[item.source] ?? item.source}</Badge>
            )}
            <Badge>{STATUS_LABELS[item.status]}</Badge>
          </div>

          <div className="flex gap-3 flex-wrap">
            <button
              type="button"
              onClick={() => setAction('include')}
              className={`flex-1 py-2 rounded border text-sm transition-colors ${
                action === 'include'
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-input hover:bg-muted'
              }`}
            >
              收录
            </button>
            <button
              type="button"
              onClick={() => setAction('exclude')}
              className={`flex-1 py-2 rounded border text-sm transition-colors ${
                action === 'exclude'
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-input hover:bg-muted'
              }`}
            >
              排除（不收录）
            </button>
            {item.status !== 'pending' && (
              <button
                type="button"
                onClick={() => setAction('pending')}
                className={`flex-1 py-2 rounded border text-sm transition-colors ${
                  action === 'pending'
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-input hover:bg-muted'
                }`}
              >
                打回审核
              </button>
            )}
          </div>

          {action === 'include' && (
            <div className="space-y-1">
              <Label htmlFor="bgm-id">Bangumi ID</Label>
              <Input
                id="bgm-id"
                type="number"
                placeholder="输入 bgm_id"
                value={bgmId}
                onChange={(e) => setBgmId(e.target.value)}
              />
            </div>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={loading}>
            取消
          </Button>
          <Button
            onClick={() => void handleSubmit()}
            disabled={loading || (action === 'include' && !bgmId)}
          >
            {loading ? '提交中...' : '确认'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
