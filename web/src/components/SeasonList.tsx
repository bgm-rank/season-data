import { useState, useEffect } from 'react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import * as api from '@/services/api'
import type { SeasonSummary, SeasonPhase } from '@/types/api'

const PHASE_LABELS: Record<SeasonPhase, string> = {
  init: '未初始化',
  fetched: '已拉取',
  reviewing: '审核中',
  done: '审核完成',
  released: '已发布',
}

const PHASE_VARIANTS: Record<SeasonPhase, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  init: 'outline',
  fetched: 'secondary',
  reviewing: 'default',
  done: 'secondary',
  released: 'default',
}

const SEASON_LABELS: Record<string, string> = {
  winter: '冬',
  spring: '春',
  summer: '夏',
  fall: '秋',
}

interface Props {
  refreshSignal?: number
}

export function SeasonList({ refreshSignal }: Props) {
  const [seasons, setSeasons] = useState<SeasonSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    api.getSeasons()
      .then(setSeasons)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [refreshSignal])

  if (loading) return <div className="text-sm text-muted-foreground">加载中...</div>
  if (error) return <div className="text-sm text-destructive">{error}</div>

  if (seasons.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground text-sm">
          暂无季度，请创建
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-2">
      {seasons.map((s) => (
        <a key={s.id} href={`/season/${s.id}`} className="block">
          <Card className="hover:bg-muted/50 transition-colors cursor-pointer">
            <CardContent className="py-3 px-4 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <span className="font-medium">
                  {s.year} {SEASON_LABELS[s.season] ?? s.season}
                </span>
                <Badge variant={PHASE_VARIANTS[s.phase]}>{PHASE_LABELS[s.phase]}</Badge>
              </div>
              <div className="text-sm text-muted-foreground flex gap-3">
                <span>待审 {s.pending_count}</span>
                <span>收录 {s.included_count}</span>
                <span>共 {s.total_count}</span>
              </div>
            </CardContent>
          </Card>
        </a>
      ))}
    </div>
  )
}
