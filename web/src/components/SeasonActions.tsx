import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { RunProgress } from '@/components/RunProgress'
import * as api from '@/services/api'
import type { SeasonPhase } from '@/types/api'

const PHASE_LABELS: Record<SeasonPhase, string> = {
  init: '未初始化',
  fetched: '已拉取',
  reviewing: '审核中',
  done: '审核完成',
  released: '已发布',
}

interface Props {
  seasonId: string
}

export function SeasonActions({ seasonId }: Props) {
  const [phase, setPhase] = useState<SeasonPhase | null>(null)
  const [fetchedCount, setFetchedCount] = useState<number | null>(null)
  const [fetching, setFetching] = useState(false)
  const [running, setRunning] = useState(false)
  const [runningSeasonId, setRunningSeasonId] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<{ updated: number; errors: number } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getSeason(seasonId)
      .then((s) => setPhase(s.phase))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [seasonId])

  const handleFetch = async () => {
    setFetching(true)
    setError(null)
    try {
      const res = await api.fetchMal(seasonId)
      setFetchedCount(res.fetched_count)
      setPhase('fetched')
    } catch (e) {
      setError(e instanceof Error ? e.message : '拉取失败')
    } finally {
      setFetching(false)
    }
  }

  const handleRun = async () => {
    setRunning(true)
    setError(null)
    setRunningSeasonId(null)
    try {
      await api.runMatching(seasonId)
      setRunningSeasonId(seasonId)
    } catch (e) {
      setError(e instanceof Error ? e.message : '启动匹配失败')
      setRunning(false)
    }
  }

  const handleSync = async () => {
    setSyncing(true)
    setSyncResult(null)
    setError(null)
    try {
      const res = await api.syncBgm(seasonId)
      setSyncResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : '刷新失败')
    } finally {
      setSyncing(false)
    }
  }

  const handleRunDone = () => {
    setRunning(false)
    setRunningSeasonId(null)
    setPhase('reviewing')
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold">季度操作</h2>
        {phase && <Badge variant="outline">{PHASE_LABELS[phase]}</Badge>}
      </div>

      {error && (
        <div className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded">
          {error}
        </div>
      )}

      <div className="flex gap-3 flex-wrap">
        <Button onClick={() => void handleFetch()} disabled={fetching || running}>
          {fetching ? '拉取中...' : '拉取 MAL 数据'}
        </Button>
        {fetchedCount != null && (
          <span className="text-sm text-muted-foreground self-center">
            已获取 {fetchedCount} 条
          </span>
        )}

        <Button
          variant="secondary"
          onClick={() => void handleRun()}
          disabled={running || fetching || syncing}
        >
          {running ? '运行中...' : '运行匹配'}
        </Button>

        <Button
          variant="outline"
          onClick={() => void handleSync()}
          disabled={running || fetching || syncing}
        >
          {syncing ? '刷新中...' : '刷新 BGM 数据'}
        </Button>
        {syncResult && (
          <span className="text-sm text-muted-foreground self-center">
            已更新 {syncResult.updated} 条{syncResult.errors > 0 ? `，${syncResult.errors} 条失败` : ''}
          </span>
        )}
      </div>

      {runningSeasonId && (
        <RunProgress seasonId={runningSeasonId} onDone={handleRunDone} />
      )}
    </div>
  )
}
