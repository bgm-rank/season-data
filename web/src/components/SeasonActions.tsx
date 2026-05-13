import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { RunProgress } from '@/components/RunProgress'
import { useProgressStream } from '@/hooks/useProgressStream'
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
  const [syncSeasonId, setSyncSeasonId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const syncUrl = syncSeasonId ? `/api/seasons/${syncSeasonId}/sync-bgm/progress` : null
  const { progress: syncProgress, done: syncDone, error: syncError } = useProgressStream(syncUrl)

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

  useEffect(() => {
    if (syncDone || syncError) {
      setSyncing(false)
      if (syncError) setError(syncError)
    }
  }, [syncDone, syncError])

  const handleSync = async () => {
    setSyncing(true)
    setSyncSeasonId(null)
    setError(null)
    try {
      await api.syncBgm(seasonId)
      setSyncSeasonId(seasonId)
    } catch (e) {
      setError(e instanceof Error ? e.message : '刷新失败')
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
      </div>

      {runningSeasonId && (
        <RunProgress seasonId={runningSeasonId} onDone={handleRunDone} />
      )}

      {syncSeasonId && (
        <div className="space-y-2">
          {syncError ? (
            <div className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded">
              刷新出错：{syncError}
            </div>
          ) : syncDone ? (
            <div className="text-sm text-green-600 bg-green-50 px-3 py-2 rounded">
              刷新完成
              {syncProgress?.updated != null && ` — 已更新 ${syncProgress.updated} 条`}
              {syncProgress?.errors != null && syncProgress.errors > 0 && `，${syncProgress.errors} 条失败`}
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between text-sm">
                <span>刷新进度</span>
                <span className="text-muted-foreground">
                  {syncProgress?.processed ?? 0} / {syncProgress?.total ?? '?'}
                </span>
              </div>
              <div className="w-full bg-muted rounded-full h-2">
                <div
                  className="bg-primary h-2 rounded-full transition-all"
                  style={{
                    width: syncProgress?.total
                      ? `${Math.round(((syncProgress.processed ?? 0) / syncProgress.total) * 100)}%`
                      : '0%',
                  }}
                />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
