import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { RunProgress } from '@/components/RunProgress'
import { useProgressStream } from '@/hooks/useProgressStream'
import { emitItemsChanged } from '@/lib/itemEvents'
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

/** 顶栏里的季度操作条，压成一行。ReviewBoard 是另一个 island，跑完靠 itemEvents 通知。 */
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
    api
      .getSeason(seasonId)
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
      emitItemsChanged('SeasonActions')
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
      else emitItemsChanged('SeasonActions')
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
    emitItemsChanged('SeasonActions')
  }

  return (
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
      {phase && (
        <Badge variant="outline" className="text-xs">
          {PHASE_LABELS[phase]}
        </Badge>
      )}

      <Button size="xs" onClick={() => void handleFetch()} disabled={fetching || running}>
        {fetching ? '拉取中...' : '拉取 MAL'}
      </Button>
      {fetchedCount != null && <span className="text-xs text-muted-foreground">已获取 {fetchedCount} 条</span>}

      <Button size="xs" variant="secondary" onClick={() => void handleRun()} disabled={running || fetching || syncing}>
        {running ? '运行中...' : '运行匹配'}
      </Button>

      <Button size="xs" variant="outline" onClick={() => void handleSync()} disabled={running || fetching || syncing}>
        {syncing ? '刷新中...' : '刷新 BGM'}
      </Button>

      {runningSeasonId && <RunProgress seasonId={runningSeasonId} onDone={handleRunDone} />}

      {syncSeasonId && !syncError && (
        <span className="flex items-center gap-2 text-xs text-muted-foreground">
          {syncDone ? (
            <span className="text-green-600 dark:text-green-500">
              刷新完成
              {syncProgress?.updated != null && ` — 已更新 ${syncProgress.updated} 条`}
              {syncProgress?.errors != null && syncProgress.errors > 0 && `，${syncProgress.errors} 条失败`}
            </span>
          ) : (
            <>
              <span className="tabular-nums">
                刷新 {syncProgress?.processed ?? 0}/{syncProgress?.total ?? '?'}
              </span>
              <span className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
                <span
                  className="block h-full rounded-full bg-primary transition-all"
                  style={{
                    width: syncProgress?.total
                      ? `${Math.round(((syncProgress.processed ?? 0) / syncProgress.total) * 100)}%`
                      : '0%',
                  }}
                />
              </span>
            </>
          )}
        </span>
      )}

      {error && <span className="truncate text-xs text-destructive">{error}</span>}
    </div>
  )
}
