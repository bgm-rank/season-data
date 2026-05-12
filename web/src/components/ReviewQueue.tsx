import { useState, useEffect, useCallback, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { CandidatePanel } from '@/components/CandidatePanel'
import * as api from '@/services/api'
import type { Item } from '@/types/api'

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
    api.getItems(seasonId, { status: 'pending' })
      .then((items) => {
        const sorted = [...items].sort((a, b) => {
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

  const confirmManualBgmId = useCallback(async () => {
    if (!currentItem) return
    const bgm_id = parseInt(manualBgmId.trim(), 10)
    if (!bgm_id || bgm_id <= 0) return
    const snapshot = state.items
    setManualBgmId('')
    advanceQueue()
    try {
      await api.patchItem(seasonId, currentItem.mal_id, { action: 'include', bgm_id })
    } catch {
      setState((s) => ({ ...s, items: snapshot, error: '操作失败，已回滚' }))
    }
  }, [currentItem, manualBgmId, state.items, seasonId, advanceQueue])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (/^[1-9]$/.test(e.key)) selectCandidate(parseInt(e.key) - 1)
      if (e.key === 'x' || e.key === 'X') void excludeItem()
      if (e.key === 's' || e.key === 'S') skipItem()
      if (e.key === 'Enter') void confirmSelection()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [selectCandidate, excludeItem, confirmSelection, skipItem])

  useEffect(() => { setManualBgmId('') }, [state.currentIndex])

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
            <div className="flex gap-2 flex-wrap">
              <Badge variant="outline">{currentItem.mal_media_type}</Badge>
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
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
