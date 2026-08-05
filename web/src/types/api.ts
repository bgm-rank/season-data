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

/** Quality issues derived server-side (src/api/quality.py), never persisted. */
export type IssueKind = 'dup_in_season' | 'dup_global' | 'date_mismatch' | 'no_bgm_name'

/**
 * Why a human excluded an item. Mirrors ExcludeReason in src/api/schemas.py —
 * there is no DB CHECK, so these two declarations are the only constraint.
 * Labels live in @/lib/reasons.
 */
export type ExcludeReason =
  | 'not_on_bgm'
  | 'merged_into_ep'
  | 'not_anime'
  | 'duplicate'
  | 'wrong_season'
  | 'other'

/** Hard-rule conflict codes, mirrors CONFLICT_* in core/processor.py. */
export type CandidateConflict = 'date' | 'platform'

export interface CandidateEntry {
  bgm_id: number
  bgm_name: string | null
  /** Added in processor fix (R2). May be absent in data processed before fix. */
  air_date?: string | null
  confidence: number | null
  /** LLM's stated reason. Only the high-mode prompt asks for it; absent otherwise. */
  reason?: string | null
  /** Code-side conflicts that forced an otherwise-confident match back to pending. */
  conflicts?: CandidateConflict[]
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
  bgm_air_date: string | null
  /** Human exclude reason; always null unless status === 'excluded'. */
  reason: ExcludeReason | null
  note: string | null
  /** Joined from the overrides table. Read-only here — write via the overrides routes. */
  override_action: OverrideAction | null
  override_reason: ExcludeReason | null
  override_target_season_id: string | null
  updated_at: string
  issues: IssueKind[]
}

/** A studio (mal_anime.studios) or a BGM tag (bgm_subject.tags) — both stored as JSON arrays. */
export interface NamedEntry {
  name: string
  [k: string]: unknown
}

/**
 * Single-item detail. Mirrors ItemDetailRead in src/api/schemas.py.
 *
 * These extra columns deliberately stay out of items_flat (that view's columns map
 * 1:1 onto ItemRead), so they only come from GET /items/{mal_id}, never the list.
 */
export interface ItemDetail extends Item {
  origin: string
  // mal_anime extras (backfilled by scripts/backfill_mal.py)
  mal_title_en: string | null
  mal_start_date: string | null
  mal_end_date: string | null
  mal_num_episodes: number | null
  /** Adaptation source (manga/light_novel/…). Prefixed because `source` is already taken. */
  mal_source: string | null
  mal_studios: NamedEntry[] | null
  mal_synopsis: string | null
  mal_fetched_at: string | null
  // bgm_subject extras
  bgm_type: number | null
  bgm_platform: string | null
  bgm_summary: string | null
  bgm_tags: NamedEntry[] | null
  bgm_nsfw: number | null
  /** null means a skeleton row — the ID is known but details were never fetched. */
  bgm_fetched_at: string | null
  // overrides columns the view doesn't carry
  override_bgm_id: number | null
  override_note: string | null
  override_created_at: string | null
}

/** List envelope. `total` is the unpaginated count so the UI can tell it was truncated. */
export interface ItemListResponse {
  total: number
  limit: number
  offset: number
  items: Item[]
  /** Season-wide counts per issue kind, unaffected by the `issue` filter. */
  issue_counts: Partial<Record<IssueKind, number>>
}

export interface ItemUpdate {
  action: 'include' | 'exclude' | 'pending'
  bgm_id?: number | null
  /** Only accepted with action='exclude'; sending it otherwise is a 422. Optional. */
  reason?: ExcludeReason | null
  /** Required when reason==='other', optional otherwise. */
  note?: string | null
}

// ─── Overrides ────────────────────────────────────────────────────────────

export type OverrideAction = 'add' | 'skip'

export interface Override {
  mal_id: number
  season_id: string
  action: OverrideAction
  bgm_id: number | null
  reason: ExcludeReason | null
  /** Hint only: where a skipped entry should go. Never auto-writes to that season. */
  target_season_id: string | null
  note: string | null
  /** null for rows created before the reason migration. */
  created_at: string | null
  /** Joined from mal_anime, read-only. */
  mal_title: string | null
  /**
   * false = this override has no season_items row yet (a to-do waiting for `run`).
   * The review board renders those as synthetic rows in the list.
   */
  in_season_items: boolean
}

export interface OverrideCreate {
  mal_id: number
  action: OverrideAction
  bgm_id?: number | null
  reason?: ExcludeReason | null
  target_season_id?: string | null
  note?: string | null
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

export interface SyncStartResponse {
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
  updated?: number
  errors?: number
  message?: string
}

// ─── API Endpoints Summary ────────────────────────────────────────────────
//
// GET    /api/seasons                           → SeasonSummary[]
// POST   /api/seasons                           body: SeasonCreate → SeasonDetail (201)
// GET    /api/seasons/{id}                      → SeasonDetail
// POST   /api/seasons/{id}/fetch                → { fetched_count: number }
// POST   /api/seasons/{id}/run?retry=false      → RunStartResponse (202)
// GET    /api/seasons/{id}/run/progress         → SSE: ProgressEvent[]
// GET    /api/seasons/{id}/items                → ItemListResponse  (query: status?, source?, issue?, limit?, offset?)
//        always ordered by mal_id ASC
// GET    /api/seasons/{id}/items/{mal_id}       → ItemDetail (404 if not in season_items)
// PATCH  /api/seasons/{id}/items/{mal_id}       body: ItemUpdate → Item
//        422 when reason/note is sent with a non-exclude action, or reason='other' has no note
// POST   /api/seasons/{id}/items/{mal_id}/sync-bgm → Item
// POST   /api/seasons/{id}/sync-bgm             → SyncStartResponse (202)
// GET    /api/seasons/{id}/sync-bgm/progress    → SSE: ProgressEvent[]
// GET    /api/seasons/{id}/overrides            → Override[]
// POST   /api/seasons/{id}/overrides            body: OverrideCreate → Override (201)
// DELETE /api/seasons/{id}/overrides/{mal_id}   → 204
// GET    /api/bgm/search?q=&season=             → BgmSearchResult[]
