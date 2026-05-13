import type {
  SeasonSummary,
  SeasonDetail,
  SeasonCreate,
  Item,
  ItemUpdate,
  Override,
  OverrideCreate,
  BgmSearchResult,
  RunStartResponse,
  SyncStartResponse,
  ExportResult,
  ReleasePreview,
} from '@/types/api'

const BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${init?.method ?? 'GET'} ${path} failed ${res.status}: ${text}`)
  }
  if (res.status === 204) return undefined as unknown as T
  return res.json() as Promise<T>
}

export function getSeasons(): Promise<SeasonSummary[]> {
  return request('/seasons')
}

export function createSeason(body: SeasonCreate): Promise<SeasonDetail> {
  return request('/seasons', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function getSeason(id: string): Promise<SeasonDetail> {
  return request(`/seasons/${id}`)
}

export function fetchMal(id: string): Promise<{ fetched_count: number }> {
  return request(`/seasons/${id}/fetch`, { method: 'POST' })
}

export function runMatching(id: string, retry = false): Promise<RunStartResponse> {
  return request(`/seasons/${id}/run?retry=${retry}`, { method: 'POST' })
}

export function syncBgm(id: string): Promise<SyncStartResponse> {
  return request(`/seasons/${id}/sync-bgm`, { method: 'POST' })
}

export function getItems(
  id: string,
  params?: { status?: string; source?: string; limit?: number; offset?: number }
): Promise<Item[]> {
  const qs = new URLSearchParams()
  if (params?.status) qs.set('status', params.status)
  if (params?.source) qs.set('source', params.source)
  if (params?.limit != null) qs.set('limit', String(params.limit))
  if (params?.offset != null) qs.set('offset', String(params.offset))
  const query = qs.toString() ? `?${qs}` : ''
  return request(`/seasons/${id}/items${query}`)
}

export function patchItem(id: string, malId: number, body: ItemUpdate): Promise<Item> {
  return request(`/seasons/${id}/items/${malId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function syncBgmItem(id: string, malId: number): Promise<Item> {
  return request(`/seasons/${id}/items/${malId}/sync-bgm`, { method: 'POST' })
}

export function getOverrides(id: string): Promise<Override[]> {
  return request(`/seasons/${id}/overrides`)
}

export function createOverride(id: string, body: OverrideCreate): Promise<Override> {
  return request(`/seasons/${id}/overrides`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function deleteOverride(id: string, malId: number): Promise<void> {
  return request(`/seasons/${id}/overrides/${malId}`, { method: 'DELETE' })
}

export function exportRelease(id: string): Promise<ExportResult> {
  return request(`/seasons/${id}/export/release`, { method: 'POST' })
}

export function exportSnapshot(id: string): Promise<ExportResult> {
  return request(`/seasons/${id}/export/snapshot`, { method: 'POST' })
}

export function getRelease(id: string): Promise<ReleasePreview> {
  return request(`/seasons/${id}/release`)
}

export function searchBgm(q: string, season?: string): Promise<BgmSearchResult[]> {
  const qs = new URLSearchParams({ q })
  if (season) qs.set('season', season)
  return request(`/bgm/search?${qs}`)
}
