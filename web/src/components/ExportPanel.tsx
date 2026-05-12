import { useState } from 'react'
import { Button } from '@/components/ui/button'
import * as api from '@/services/api'

interface Props {
  seasonId: string
}

export function ExportPanel({ seasonId }: Props) {
  const [exportingRelease, setExportingRelease] = useState(false)
  const [exportingSnapshot, setExportingSnapshot] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const triggerDownload = (json: unknown, filename: string) => {
    const blob = new Blob([JSON.stringify(json, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleExportRelease = async () => {
    setExportingRelease(true)
    setError(null)
    setMessage(null)
    try {
      const result = await api.exportRelease(seasonId)
      const preview = await api.getRelease(seasonId)
      triggerDownload(preview, `${seasonId}-release.json`)
      setMessage(`导出完成：${result.item_count} 条，文件已保存至 ${result.path}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '导出失败')
    } finally {
      setExportingRelease(false)
    }
  }

  const handleExportSnapshot = async () => {
    setExportingSnapshot(true)
    setError(null)
    setMessage(null)
    try {
      const result = await api.exportSnapshot(seasonId)
      setMessage(`快照已保存：${result.path}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '导出快照失败')
    } finally {
      setExportingSnapshot(false)
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">导出</h2>

      <div className="flex gap-3 flex-wrap">
        <Button onClick={() => void handleExportRelease()} disabled={exportingRelease}>
          {exportingRelease ? '导出中...' : '导出 Release'}
        </Button>
        <Button
          variant="outline"
          onClick={() => void handleExportSnapshot()}
          disabled={exportingSnapshot}
        >
          {exportingSnapshot ? '导出中...' : '导出快照'}
        </Button>
      </div>

      {message && (
        <p className="text-sm text-green-600 bg-green-50 px-3 py-2 rounded">{message}</p>
      )}
      {error && (
        <p className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded">{error}</p>
      )}
    </div>
  )
}
