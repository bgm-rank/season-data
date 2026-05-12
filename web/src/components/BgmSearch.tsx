import { useState, useCallback, useRef } from 'react'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import * as api from '@/services/api'
import type { BgmSearchResult } from '@/types/api'

interface Props {
  seasonId: string
  onSelect: (result: BgmSearchResult) => void
}

export function BgmSearch({ seasonId, onSelect }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<BgmSearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [searched, setSearched] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const q = e.target.value
      setQuery(q)
      if (timerRef.current) clearTimeout(timerRef.current)
      if (!q.trim()) {
        setResults([])
        setSearched(false)
        return
      }
      timerRef.current = setTimeout(async () => {
        setSearching(true)
        setSearchError(null)
        try {
          const res = await api.searchBgm(q, seasonId)
          setResults(res)
          setSearched(true)
        } catch (err) {
          setSearchError(
            err instanceof Error ? err.message : '搜索失败，请检查网络后重试'
          )
        } finally {
          setSearching(false)
        }
      }, 500)
    },
    [seasonId]
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'x' || e.key === 'X') e.stopPropagation()
    },
    []
  )

  return (
    <div className="space-y-3">
      <div>
        <p className="text-sm text-muted-foreground mb-2">无候选结果，请手动搜索 Bangumi</p>
        <Input
          placeholder="输入关键词搜索（500ms 后自动触发）"
          value={query}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          autoFocus
        />
      </div>

      {searching && (
        <p className="text-sm text-muted-foreground">搜索中...</p>
      )}

      {searchError && (
        <p className="text-sm text-destructive">{searchError}</p>
      )}

      {searched && !searching && results.length === 0 && (
        <p className="text-sm text-muted-foreground">未找到结果</p>
      )}

      {results.length > 0 && (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {results.map((r) => (
            <Card
              key={r.bgm_id}
              className="cursor-pointer hover:bg-muted/50 transition-colors"
              onClick={() => onSelect(r)}
            >
              <CardContent className="py-3 px-4">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-sm">{r.bgm_name ?? `bgm:${r.bgm_id}`}</span>
                  {r.bgm_name_cn && (
                    <span className="text-xs text-muted-foreground">{r.bgm_name_cn}</span>
                  )}
                  <Badge variant="outline" className="text-xs shrink-0">bgm:{r.bgm_id}</Badge>
                </div>
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  {r.air_date ? (
                    <span className="text-xs text-muted-foreground">{r.air_date}</span>
                  ) : (
                    <Badge variant="secondary" className="text-xs">日期未知</Badge>
                  )}
                  {r.media_type && (
                    <Badge variant="outline" className="text-xs">{r.media_type}</Badge>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
