import { useProgressStream } from '@/hooks/useProgressStream'

interface Props {
  seasonId: string
  onDone?: () => void
}

export function RunProgress({ seasonId, onDone }: Props) {
  const { progress, done, error } = useProgressStream(seasonId)

  if (error) {
    return (
      <div className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded">
        匹配出错：{error}
      </div>
    )
  }

  if (done) {
    if (onDone) onDone()
    return (
      <div className="text-sm text-green-600 bg-green-50 px-3 py-2 rounded">
        匹配完成
        {progress?.total != null && ` — 共处理 ${progress.total} 条`}
      </div>
    )
  }

  if (!progress) {
    return <div className="text-sm text-muted-foreground">连接中...</div>
  }

  const pct =
    progress.total && progress.total > 0
      ? Math.round(((progress.processed ?? 0) / progress.total) * 100)
      : 0

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span>匹配进度</span>
        <span className="text-muted-foreground">
          {progress.processed ?? 0} / {progress.total ?? '?'}
        </span>
      </div>
      <div className="w-full bg-muted rounded-full h-2">
        <div
          className="bg-primary h-2 rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex gap-4 text-xs text-muted-foreground">
        {progress.pending != null && <span>待审 {progress.pending}</span>}
        {progress.included != null && <span>收录 {progress.included}</span>}
        {progress.excluded != null && <span>排除 {progress.excluded}</span>}
      </div>
    </div>
  )
}
