import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import type { CandidateConflict, CandidateEntry } from '@/types/api'

interface Props {
  candidates: CandidateEntry[]
  selectedIndex: number | null
  onSelect: (index: number) => void
}

const CONFLICT_LABELS: Record<CandidateConflict, string> = {
  date: '日期不符',
  platform: '类型不符',
}

export function CandidatePanel({ candidates, selectedIndex, onSelect }: Props) {
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground mb-2">选择候选（数字键 1-9）</p>
      {candidates.map((c, i) => (
        <Card
          key={c.bgm_id}
          className={`cursor-pointer transition-colors ${
            selectedIndex === i ? 'ring-2 ring-primary bg-primary/5' : 'hover:bg-muted/50'
          }`}
          onClick={() => onSelect(i)}
        >
          <CardContent className="py-3 px-4 flex items-start gap-3">
            <span className="text-sm font-mono text-muted-foreground w-4 shrink-0">{i + 1}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-sm truncate">{c.bgm_name ?? `bgm:${c.bgm_id}`}</span>
                <Badge variant="outline" className="text-xs shrink-0">bgm:{c.bgm_id}</Badge>
              </div>
              <div className="flex items-center gap-2 mt-1 flex-wrap">
                {c.air_date ? (
                  <span className="text-xs text-muted-foreground">{c.air_date}</span>
                ) : (
                  <Badge variant="secondary" className="text-xs">日期未知</Badge>
                )}
                {c.confidence != null && (
                  <span className="text-xs text-muted-foreground">
                    置信度 {(c.confidence * 100).toFixed(0)}%
                  </span>
                )}
                {c.conflicts?.map((k) => (
                  <Badge key={k} variant="destructive" className="text-xs">
                    {CONFLICT_LABELS[k] ?? k}
                  </Badge>
                ))}
              </div>
              {c.reason && <p className="text-xs text-muted-foreground mt-1">{c.reason}</p>}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
