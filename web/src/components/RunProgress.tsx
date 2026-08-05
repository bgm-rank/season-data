import { useProgressStream } from '@/hooks/useProgressStream'

interface Props {
  seasonId: string
  onDone?: () => void
}

/** 顶栏里的一条进度，压成单行——审核台把整个视口都占了，容不下方块状的进度卡片。 */
export function RunProgress({ seasonId, onDone }: Props) {
  const { progress, done, error } = useProgressStream(`/api/seasons/${seasonId}/run/progress`)

  if (error) {
    return <span className="text-xs text-destructive">匹配出错：{error}</span>
  }

  if (done) {
    if (onDone) onDone()
    return (
      <span className="text-xs text-green-600 dark:text-green-500">
        匹配完成{progress?.total != null && ` — 共 ${progress.total} 条`}
      </span>
    )
  }

  if (!progress) {
    return <span className="text-xs text-muted-foreground">连接中...</span>
  }

  const pct =
    progress.total && progress.total > 0 ? Math.round(((progress.processed ?? 0) / progress.total) * 100) : 0

  return (
    <span className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className="tabular-nums">
        匹配 {progress.processed ?? 0}/{progress.total ?? '?'}
      </span>
      <span className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
        <span className="block h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </span>
      {progress.pending != null && <span>待审 {progress.pending}</span>}
      {progress.included != null && <span>收录 {progress.included}</span>}
      {progress.excluded != null && <span>排除 {progress.excluded}</span>}
    </span>
  )
}
