/**
 * API contract types — mirrors backend Pydantic schemas in src/api/schemas.py
 * These types are the source of truth for web/src/services/api.ts
 *
 * API base URL: /api (proxied by Astro dev server to http://localhost:8000)
 */

// ─── Seasons ──────────────────────────────────────────────────────────────

export type SeasonPhase = 'init' | 'fetched' | 'reviewing' | 'done' | 'released'
export type SeasonName = 'winter' | 'spring' | 'summer' | 'fall'

export interface SeasonSummary {
  id: string
  year: number
  season: SeasonName
  phase: SeasonPhase
  total_count: number
  pending_count: number
  included_count: number
  excluded_count: number
  released_at: string | null
  updated_at: string
}

export interface SeasonDetail extends SeasonSummary {
  created_at: string
}

export interface SeasonCreate {
  year: number
  season: SeasonName
}

// ─── Items ────────────────────────────────────────────────────────────────

export type ItemStatus = 'pending' | 'included' | 'excluded'
export type ItemSource = 'rule' | 'exact' | 'llm' | 'human'

export interface CandidateEntry {
  bgm_id: number
  bgm_name: string | null
  /** Added in processor fix (R2). May be absent in data processed before fix. */
  air_date?: string | null
  confidence: number | null
}

export interface Item {
  mal_id: number
  season_id: string
  status: ItemStatus
  source: ItemSource | null
  confidence: number | null
  bgm_id: number | null
  bgm_name: string | null
  bgm_name_cn: string | null
  mal_title: string
  mal_title_ja: string | null
  mal_media_type: string
  mal_rating: string
  error: string | null
  candidates: CandidateEntry[] | null
  updated_at: string
}

export interface ItemUpdate {
  action: 'include' | 'exclude'
  bgm_id?: number | null
}

// ─── Overrides ────────────────────────────────────────────────────────────

export type OverrideAction = 'add' | 'skip'

export interface Override {
  mal_id: number
  season_id: string
  action: OverrideAction
  bgm_id: number | null
}

export interface OverrideCreate {
  mal_id: number
  action: OverrideAction
  bgm_id?: number | null
}

// ─── BGM Search ───────────────────────────────────────────────────────────

export interface BgmSearchResult {
  bgm_id: number
  bgm_name: string | null
  bgm_name_cn: string | null
  air_date: string | null
  media_type: string | null
}

// ─── Run / SSE ────────────────────────────────────────────────────────────

export interface RunStartResponse {
  task_id: string
}

export type ProgressEventType = 'progress' | 'done' | 'error' | 'heartbeat'

export interface ProgressEvent {
  type: ProgressEventType
  processed?: number
  total?: number
  pending?: number
  included?: number
  excluded?: number
  message?: string
}

// ─── Export ───────────────────────────────────────────────────────────────

export interface ReleasePreview {
  season: string
  items: ReleaseItem[]
}

export interface ReleaseItem {
  bgm_id: number
  bgm_name?: string
  bgm_name_cn?: string
  mal: {
    id: number
    title: string
    title_ja?: string
    media_type: string
    rating: string
  }
}

export interface ExportResult {
  path: string
  item_count: number
}

// ─── API Endpoints Summary ────────────────────────────────────────────────
//
// GET    /api/seasons                           → SeasonSummary[]
// POST   /api/seasons                           body: SeasonCreate → SeasonDetail (201)
// GET    /api/seasons/{id}                      → SeasonDetail
// POST   /api/seasons/{id}/fetch                → { fetched_count: number }
// POST   /api/seasons/{id}/run?retry=false      → RunStartResponse (202)
// GET    /api/seasons/{id}/run/progress         → SSE: ProgressEvent[]
// GET    /api/seasons/{id}/items                → Item[]  (query: status?, source?, limit?, offset?)
// PATCH  /api/seasons/{id}/items/{mal_id}       body: ItemUpdate → Item
// GET    /api/seasons/{id}/overrides            → Override[]
// POST   /api/seasons/{id}/overrides            body: OverrideCreate → Override (201)
// DELETE /api/seasons/{id}/overrides/{mal_id}   → 204
// GET    /api/seasons/{id}/release              → ReleasePreview
// POST   /api/seasons/{id}/export/release       → ExportResult
// POST   /api/seasons/{id}/export/snapshot      → ExportResult
// GET    /api/bgm/search?q=&season=             → BgmSearchResult[]
