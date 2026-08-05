import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { reasonLabel } from '@/lib/reasons'
import * as api from '@/services/api'
import type { Override, OverrideAction, SeasonSummary } from '@/types/api'

interface Props {
  seasonId: string
}

export function OverrideManager({ seasonId }: Props) {
  const [overrides, setOverrides] = useState<Override[]>([])
  const [loading, setLoading] = useState(true)
  const [malId, setMalId] = useState('')
  const [action, setAction] = useState<OverrideAction>('skip')
  const [bgmId, setBgmId] = useState('')
  const [targetSeasonId, setTargetSeasonId] = useState('')
  const [seasons, setSeasons] = useState<SeasonSummary[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadOverrides = () => {
    api.getOverrides(seasonId)
      .then(setOverrides)
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadOverrides()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seasonId])

  useEffect(() => {
    api.getSeasons().then(setSeasons).catch(() => {})
  }, [])

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!malId) return
    setSubmitting(true)
    setError(null)
    try {
      await api.createOverride(seasonId, {
        mal_id: parseInt(malId),
        action,
        bgm_id: action === 'add' && bgmId ? parseInt(bgmId) : undefined,
        // skip 只有一种原因：这条番该去别的季度。目标季度是选填的线索
        reason: action === 'skip' ? 'wrong_season' : undefined,
        target_season_id: action === 'skip' && targetSeasonId ? targetSeasonId : undefined,
      })
      setMalId('')
      setBgmId('')
      setTargetSeasonId('')
      loadOverrides()
    } catch (err) {
      setError(err instanceof Error ? err.message : '添加失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (malIdNum: number) => {
    try {
      await api.deleteOverride(seasonId, malIdNum)
      loadOverrides()
    } catch {
      setError('删除失败')
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Override 管理</h2>

      <form onSubmit={(e) => void handleAdd(e)} className="flex items-end gap-3 flex-wrap">
        <div className="space-y-1">
          <Label htmlFor="override-mal-id">MAL ID</Label>
          <Input
            id="override-mal-id"
            type="number"
            placeholder="MAL ID"
            value={malId}
            onChange={(e) => setMalId(e.target.value)}
            className="w-32"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="override-action">操作</Label>
          <select
            id="override-action"
            value={action}
            onChange={(e) => setAction(e.target.value as OverrideAction)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="skip">skip（排除）</option>
            <option value="add">add（强制收录）</option>
          </select>
        </div>
        {action === 'add' && (
          <div className="space-y-1">
            <Label htmlFor="override-bgm-id">BGM ID</Label>
            <Input
              id="override-bgm-id"
              type="number"
              placeholder="BGM ID"
              value={bgmId}
              onChange={(e) => setBgmId(e.target.value)}
              className="w-32"
            />
          </div>
        )}
        {action === 'skip' && (
          <div className="space-y-1">
            <Label htmlFor="override-target-season">该去哪个季度（选填）</Label>
            <select
              id="override-target-season"
              value={targetSeasonId}
              onChange={(e) => setTargetSeasonId(e.target.value)}
              className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">不确定</option>
              {seasons
                .filter((s) => s.id !== seasonId)
                .sort((a, b) => b.id.localeCompare(a.id))
                .map((s) => (
                  <option key={s.id} value={s.id}>{s.id}</option>
                ))}
            </select>
          </div>
        )}
        <Button type="submit" disabled={submitting || !malId}>
          {submitting ? '添加中...' : '添加'}
        </Button>
        {error && <p className="text-sm text-destructive w-full">{error}</p>}
      </form>

      {loading ? (
        <div className="text-sm text-muted-foreground">加载中...</div>
      ) : overrides.length === 0 ? (
        <Card>
          <CardContent className="py-4 text-center text-sm text-muted-foreground">
            暂无 override
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {overrides.map((o) => (
            <Card key={o.mal_id}>
              <CardContent className="py-3 px-4 flex items-center justify-between">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-mono">mal:{o.mal_id}</span>
                  <Badge variant={o.action === 'skip' ? 'secondary' : 'default'}>
                    {o.action}
                  </Badge>
                  {o.bgm_id ? (
                    <span className="text-xs text-muted-foreground">bgm:{o.bgm_id}</span>
                  ) : o.action === 'add' ? (
                    // 合法状态：先记下「该挪进本季」，bgm_id 待查。run 会跳过并提示
                    <span className="text-xs text-amber-600 dark:text-amber-500">bgm_id 待补</span>
                  ) : null}
                  {o.reason && (
                    <span className="text-xs text-muted-foreground">{reasonLabel(o.reason)}</span>
                  )}
                  {o.target_season_id && (
                    <span className="text-xs text-muted-foreground">→ {o.target_season_id}</span>
                  )}
                  {o.note && (
                    <span className="text-xs text-muted-foreground italic">{o.note}</span>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void handleDelete(o.mal_id)}
                  className="text-destructive hover:text-destructive"
                >
                  删除
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
