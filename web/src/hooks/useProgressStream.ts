import { useState, useEffect } from 'react'
import type { ProgressEvent } from '@/types/api'

export function useProgressStream(seasonId: string | null) {
  const [progress, setProgress] = useState<ProgressEvent | null>(null)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!seasonId) return
    const es = new EventSource(`/api/seasons/${seasonId}/run/progress`)
    es.onmessage = (e: MessageEvent) => {
      const data = JSON.parse(e.data as string) as ProgressEvent
      if (data.type === 'progress') setProgress(data)
      if (data.type === 'done') {
        setProgress(data)
        setDone(true)
        es.close()
      }
      if (data.type === 'error') {
        setError(data.message ?? 'Unknown error')
        es.close()
      }
    }
    es.onerror = () => {
      es.close()
    }
    return () => es.close()
  }, [seasonId])

  return { progress, done, error }
}
