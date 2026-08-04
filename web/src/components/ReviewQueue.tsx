import { useState, useEffect, useCallback, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { CandidatePanel } from '@/components/CandidatePanel'
import { emitItemsChanged, onItemsChanged } from '@/lib/itemEvents'
import * as api from '@/services/api'
import type { Item, SeasonSummary } from '@/types/api'

interface ReviewQueueState {
  items: Item[]
  currentIndex: number
  selectedCandidate: number | null
  loading: boolean
  error: string | null
}

interface Props {
  seasonId: string
}

export function ReviewQueue({ seasonId }: Props) {
  const [state, setState] = useState<ReviewQueueState>({
    items: [],
    currentIndex: 0,
    selectedCandidate: null,
    loading: true,
    error: null,
  })

  const [loadSignal, setLoadSignal] = useState(0)

  useEffect(() => {
    setState((s) => ({ ...s, loading: true, error: null }))
    api.getItems(seasonId, { status: 'pending', limit: 1000 })
      .then((res) => {
        const sorted = [...res.items].sort((a, b) => {
          const ca = a.confidence ?? -1
          const cb = b.confidence ?? -1
          return ca - cb
        })
        setState((s) => ({ ...s, items: sorted, loading: false, currentIndex: 0, selectedCandidate: null }))
      })
      .catch((e: unknown) => {
        setState((s) => ({
          ...s,
          loading: false,
          error: e instanceof Error ? e.message : String(e),
        }))
      })
  }, [seasonId, loadSignal])

  const refreshQueue = useCallback(() => setLoadSignal((n) => n + 1), [])

  // ItemList 改了条目后队列可能过期。刻意只提示不自动重载——重载会把正在审核的
  // 条目从手底下抽走。错误横幅本来就带「刷新队列」按钮。
  useEffect(
    () =>
      onItemsChanged('ReviewQueue', () =>
        setState((s) => ({ ...s, error: '列表已变更，队列可能过期' }))
      ),
    []
  )

  const currentItem = state.items[state.currentIndex] ?? null

  const advanceQueue = useCallback(() => {
    setState((s) => {
      const next = [...s.items]
      next.splice(s.currentIndex, 1)
      return {
        ...s,
        items: next,
        currentIndex: Math.min(s.currentIndex, Math.max(next.length - 1, 0)),
        selectedCandidate: null,
        error: null,
      }
    })
  }, [])

  const confirmSelection = useCallback(async () => {
    if (!currentItem) return
    const idx = state.selectedCandidate
    const candidates = currentItem.candidates
    if (candidates && idx != null && candidates[idx]) {
      const bgm_id = candidates[idx].bgm_id
      const snapshot = state.items
      advanceQueue()
      try {
        await api.patchItem(seasonId, currentItem.mal_id, { action: 'include', bgm_id })
        emitItemsChanged('ReviewQueue')
      } catch (e) {
        const msg = e instanceof Error && e.message.includes('409')
          ? '数据已变更，请刷新队列'
          : '操作失败，已回滚'
        setState((s) => ({ ...s, items: snapshot, error: msg }))
      }
    }
  }, [currentItem, state.selectedCandidate, state.items, seasonId, advanceQueue])

  const excludeItem = useCallback(async () => {
    if (!currentItem) return
    const snapshot = state.items
    advanceQueue()
    try {
      await api.patchItem(seasonId, currentItem.mal_id, { action: 'exclude' })
      emitItemsChanged('ReviewQueue')
    } catch (e) {
      const msg = e instanceof Error && e.message.includes('409')
        ? '数据已变更，请刷新队列'
        : '操作失败，已回滚'
      setState((s) => ({ ...s, items: snapshot, error: msg }))
    }
  }, [currentItem, state.items, seasonId, advanceQueue])

  const skipItem = useCallback(() => {
    setState((s) => {
      if (s.items.length <= 1) return s
      const next = [...s.items]
      const [current] = next.splice(s.currentIndex, 1)
      next.push(current)
      return { ...s, items: next, currentIndex: 0, selectedCandidate: null }
    })
  }, [])

  const selectCandidate = useCallback((idx: number) => {
    setState((s) => ({ ...s, selectedCandidate: idx }))
  }, [])

  const [manualBgmId, setManualBgmId] = useState('')
  const manualInputRef = useRef<HTMLInputElement>(null)

  const [seasons, setSeasons] = useState<SeasonSummary[]>([])
  const [moveOpen, setMoveOpen] = useState(false)
  const [targetSeasonId, setTargetSeasonId] = useState('')
  const [moveBgmId, setMoveBgmId] = useState('')
  const [moveError, setMoveError] = useState<string | null>(null)
  const [moveSubmitting, setMoveSubmitting] = useState(false)

  useEffect(() => {
    api.getSeasons().then(setSeasons).catch(() => {})
  }, [])

  const confirmManualBgmId = useCallback(async () => {
    if (!currentItem) return
    const bgm_id = parseInt(manualBgmId.trim(), 10)
    if (!bgm_id || bgm_id <= 0) return
    const snapshot = state.items
    setManualBgmId('')
    advanceQueue()
    try {
      await api.patchItem(seasonId, currentItem.mal_id, { action: 'include', bgm_id })
      emitItemsChanged('ReviewQueue')
    } catch {
      setState((s) => ({ ...s, items: snapshot, error: '操作失败，已回滚' }))
    }
  }, [currentItem, manualBgmId, state.items, seasonId, advanceQueue])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      const tag = target.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      // 这些监听绑在 window 上，而 ItemList 同页挂载且也用 x 排除。
      // 不挡的话按一次 x 会同时改两个组件的条目。
      if (target.closest?.('[data-keyscope]')) return
      if (/^[1-9]$/.test(e.key)) selectCandidate(parseInt(e.key) - 1)
      if (e.key === 'x' || e.key === 'X') void excludeItem()
      if (e.key === 's' || e.key === 'S') skipItem()
      if (e.key === 'Enter') void confirmSelection()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [selectCandidate, excludeItem, confirmSelection, skipItem])

  const moveToSeason = useCallback(async () => {
    if (!currentItem || !targetSeasonId || !moveBgmId) return
    const bgm_id = parseInt(moveBgmId, 10)
    if (!bgm_id || bgm_id <= 0) return
    setMoveSubmitting(true)
    setMoveError(null)
    const snapshot = state.items
    try {
      await api.patchItem(seasonId, currentItem.mal_id, { action: 'exclude' })
      await api.createOverride(targetSeasonId, { mal_id: currentItem.mal_id, action: 'add', bgm_id })
      setMoveOpen(false)
      setMoveBgmId('')
      setTargetSeasonId('')
      advanceQueue()
    } catch (e) {
      setState((s) => ({ ...s, items: snapshot }))
      setMoveError(e instanceof Error ? e.message : '操作失败')
    } finally {
      setMoveSubmitting(false)
    }
  }, [currentItem, targetSeasonId, moveBgmId, seasonId, state.items, advanceQueue])

  useEffect(() => { setManualBgmId(''); setMoveOpen(false); setMoveError(null) }, [state.currentIndex])

  if (state.loading) {
    return <div className="text-sm text-muted-foreground p-4">加载中...</div>
  }

  if (state.items.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center">
          <p className="text-lg font-medium mb-1">审核完成</p>
          <p className="text-sm text-muted-foreground">所有待审核条目已处理完毕</p>
        </CardContent>
      </Card>
    )
  }

  const hasCandidates = currentItem && currentItem.candidates && currentItem.candidates.length > 0

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          审核队列 <Badge variant="secondary">{state.items.length} 条待处理</Badge>
        </h2>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">
            {state.currentIndex + 1} / {state.items.length}
          </span>
          <button
            onClick={refreshQueue}
            className="text-xs text-muted-foreground hover:underline"
          >
            刷新
          </button>
        </div>
      </div>

      {state.error && (
        <div className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded flex items-center justify-between">
          <span>{state.error}</span>
          <button
            onClick={refreshQueue}
            className="text-xs underline ml-2 hover:no-underline"
          >
            刷新队列
          </button>
        </div>
      )}

      {currentItem && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{currentItem.mal_title}</CardTitle>
            <div className="flex gap-2 flex-wrap items-center">
              <Badge variant="outline">{currentItem.mal_media_type}</Badge>
              <span className="text-xs font-mono text-muted-foreground">MAL:{currentItem.mal_id}</span>
              {currentItem.mal_title_ja && (
                <span className="text-xs text-muted-foreground">{currentItem.mal_title_ja}</span>
              )}
              {currentItem.confidence != null && (
                <Badge variant="secondary" className="text-xs">
                  LLM 置信度 {(currentItem.confidence * 100).toFixed(0)}%
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {hasCandidates && (
              <CandidatePanel
                candidates={currentItem.candidates!}
                selectedIndex={state.selectedCandidate}
                onSelect={selectCandidate}
              />
            )}

            <div className="flex gap-2 items-center">
              <Input
                ref={manualInputRef}
                type="number"
                min={1}
                placeholder="手动输入 bgm_id"
                value={manualBgmId}
                onChange={(e) => setManualBgmId(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); void confirmManualBgmId() } }}
                className="w-48"
              />
              <Button
                variant="secondary"
                onClick={() => void confirmManualBgmId()}
                disabled={!manualBgmId.trim() || parseInt(manualBgmId.trim(), 10) <= 0}
              >
                收录此 bgm_id
              </Button>
            </div>

            <div className="flex gap-2 pt-2 border-t flex-wrap">
              {hasCandidates && (
                <Button
                  onClick={() => void confirmSelection()}
                  disabled={state.selectedCandidate == null}
                  className="flex-1"
                >
                  确认收录 (Enter)
                </Button>
              )}
              <Button
                variant="secondary"
                onClick={skipItem}
                disabled={state.items.length <= 1}
                title="移到队列末尾，稍后再审"
              >
                跳过（稍后审）
              </Button>
              <Button
                variant="outline"
                onClick={() => void excludeItem()}
              >
                排除（不收录）(X)
                <span className="ml-1 text-xs text-muted-foreground hidden sm:inline">
                  此番不属于本季度或无需收录
                </span>
              </Button>
              <Button
                variant="outline"
                onClick={() => setMoveOpen((o) => !o)}
              >
                移至其他季度
              </Button>
            </div>

            {moveOpen && (
              <div className="border rounded-md p-3 space-y-3 bg-muted/30">
                <p className="text-sm font-medium">移至其他季度（排除当前 + 在目标季度添加 override）</p>
                <div className="flex gap-2 flex-wrap items-end">
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">目标季度</label>
                    <select
                      value={targetSeasonId}
                      onChange={(e) => setTargetSeasonId(e.target.value)}
                      className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                    >
                      <option value="">选择季度...</option>
                      {seasons
                        .filter((s) => s.id !== seasonId)
                        .sort((a, b) => b.id.localeCompare(a.id))
                        .map((s) => (
                          <option key={s.id} value={s.id}>{s.id}</option>
                        ))}
                    </select>
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">BGM ID</label>
                    <Input
                      type="number"
                      min={1}
                      placeholder="BGM ID"
                      value={moveBgmId}
                      onChange={(e) => setMoveBgmId(e.target.value)}
                      className="w-32"
                    />
                  </div>
                  <Button
                    size="sm"
                    onClick={() => void moveToSeason()}
                    disabled={moveSubmitting || !targetSeasonId || !moveBgmId}
                  >
                    {moveSubmitting ? '处理中...' : '确认移至'}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => { setMoveOpen(false); setMoveBgmId(''); setMoveError(null) }}
                  >
                    取消
                  </Button>
                </div>
                {moveError && <p className="text-xs text-destructive">{moveError}</p>}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
