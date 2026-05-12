import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import * as api from '@/services/api'
import type { SeasonName } from '@/types/api'

const SEASONS: { value: SeasonName; label: string }[] = [
  { value: 'winter', label: '冬 (Winter)' },
  { value: 'spring', label: '春 (Spring)' },
  { value: 'summer', label: '夏 (Summer)' },
  { value: 'fall', label: '秋 (Fall)' },
]

interface Props {
  onCreated?: () => void
}

export function SeasonForm({ onCreated }: Props) {
  const currentYear = new Date().getFullYear()
  const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear - 2 + i)

  const [year, setYear] = useState(currentYear)
  const [season, setSeason] = useState<SeasonName>('spring')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await api.createSeason({ year, season })
      onCreated?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="flex items-end gap-3 flex-wrap">
      <div className="space-y-1">
        <Label htmlFor="year">年份</Label>
        <select
          id="year"
          value={year}
          onChange={(e) => setYear(parseInt(e.target.value))}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm"
        >
          {yearOptions.map((y) => (
            <option key={y} value={y}>{y}</option>
          ))}
        </select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="season">季节</Label>
        <select
          id="season"
          value={season}
          onChange={(e) => setSeason(e.target.value as SeasonName)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm"
        >
          {SEASONS.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
      </div>
      <Button type="submit" disabled={loading}>
        {loading ? '创建中...' : '新建季度'}
      </Button>
      {error && <p className="text-sm text-destructive w-full">{error}</p>}
    </form>
  )
}
