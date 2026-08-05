import { useEffect, useState, type ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { CandidatePanel } from '@/components/CandidatePanel'
import { ReasonPicker } from '@/components/ReasonPicker'
import { ISSUE_LABELS, SOURCE_LABELS } from '@/components/ItemRow'
import { reasonLabel } from '@/lib/reasons'
import { seasonIdLabel } from '@/lib/seasons'
import type { ExcludeReason, ItemDetail as Detail, Override, SeasonSummary } from '@/types/api'

const STATUS_LABELS: Record<string, string> = {
  pending: '待审核',
  included: '已收录',
  excluded: '已排除',
}

const MAL_SOURCE_LABELS: Record<string, string> = {
  original: '原创',
  manga: '漫画',
  light_novel: '轻小说',
  novel: '小说',
  visual_novel: '视觉小说',
  game: '游戏',
  web_manga: '网络漫画',
  '4_koma_manga': '四格漫画',
  picture_book: '绘本',
  card_game: '卡牌游戏',
  music: '音乐',
  radio: '广播剧',
  book: '书籍',
  other: '其他',
}

/** 一行「标签：值」。值为空就整行不渲染，免得详情里挂一排「—」。 */
function Field({ label, children }: { label: string; children?: ReactNode }) {
  if (children == null || children === '' || children === false) return null
  return (
    <div className="flex gap-2 text-xs">
      <span className="w-16 shrink-0 text-muted-foreground/60">{label}</span>
      <span className="min-w-0 flex-1">{children}</span>
    </div>
  )
}

function Section({ title, extra, children }: { title: string; extra?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-1.5">
      <div className="flex items-center gap-2 border-b pb-1">
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
        {extra}
      </div>
      {children}
    </section>
  )
}

/** 简介类长文本：默认收起 4 行，点一下展开。 */
function Collapsible({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <p className={`text-xs leading-relaxed whitespace-pre-wrap ${open ? '' : 'line-clamp-4'}`}>{text}</p>
      <button onClick={() => setOpen((o) => !o)} className="mt-0.5 text-xs text-muted-foreground hover:underline">
        {open ? '收起' : '展开'}
      </button>
    </div>
  )
}

interface Props {
  detail: Detail | null
  /** 选中的是「建了 override 但还没 run」的待办行，此时 detail 恒为 null */
  orphan: Override | null
  loading: boolean
  error: string | null
  busy: boolean
  seasons: SeasonSummary[]
  seasonId: string
  selectedCandidate: number | null
  onSelectCandidate: (i: number) => void
  onInclude: (bgmId: number) => void
  onExclude: (reason: ExcludeReason | null, note: string | null) => void
  onPending: () => void
  onSync: () => void
  onMove: (targetSeasonId: string, bgmId: number) => void
  onDeleteOverride: (malId: number) => void
}

export function ItemDetail({
  detail,
  orphan,
  loading,
  error,
  busy,
  seasons,
  seasonId,
  selectedCandidate,
  onSelectCandidate,
  onInclude,
  onExclude,
  onPending,
  onSync,
  onMove,
  onDeleteOverride,
}: Props) {
  const [reason, setReason] = useState<ExcludeReason | null>(null)
  const [reasonNote, setReasonNote] = useState('')
  const [manualBgmId, setManualBgmId] = useState('')
  const [moveOpen, setMoveOpen] = useState(false)
  const [targetSeasonId, setTargetSeasonId] = useState('')
  const [moveBgmId, setMoveBgmId] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  const currentMalId = detail?.mal_id ?? orphan?.mal_id ?? null

  // 换条目、或写操作成功（updated_at 变了）就把输入清干净：否则上一条填的排除原因
  // 会跟着带到下一条，「移至其他季度」的面板也会在提交后一直开着。
  // 写失败时 updated_at 不变，输入原样保留，方便改完重试。
  useEffect(() => {
    setReason(null)
    setReasonNote('')
    setManualBgmId('')
    setMoveOpen(false)
    setMoveBgmId('')
    setTargetSeasonId('')
    setLocalError(null)
  }, [currentMalId, detail?.updated_at])

  if (orphan) {
    return (
      <div className="mx-auto max-w-2xl space-y-4 p-6">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">{orphan.mal_title ?? `mal:${orphan.mal_id}`}</h2>
          <Badge variant="outline">待 run</Badge>
        </div>
        <p className="rounded bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
          这条 override 还没落进本季的条目表。运行一次匹配后它才会作为 origin=override 的条目出现，
          在那之前无法审核。
        </p>
        <Section title="Override">
          <Field label="mal_id">
            <a
              href={`https://myanimelist.net/anime/${orphan.mal_id}`}
              target="_blank"
              rel="noreferrer"
              className="text-blue-500 underline hover:text-blue-600"
            >
              {orphan.mal_id}
            </a>
          </Field>
          <Field label="动作">{orphan.action}</Field>
          <Field label="bgm_id">
            {orphan.bgm_id ? (
              <a
                href={`https://bgm.tv/subject/${orphan.bgm_id}`}
                target="_blank"
                rel="noreferrer"
                className="text-blue-500 underline hover:text-blue-600"
              >
                {orphan.bgm_id}
              </a>
            ) : (
              <span className="text-muted-foreground">待查（run 时会 WARNING 跳过）</span>
            )}
          </Field>
          <Field label="原因">{orphan.reason && reasonLabel(orphan.reason)}</Field>
          <Field label="目标季">{orphan.target_season_id && seasonIdLabel(orphan.target_season_id)}</Field>
          <Field label="备注">{orphan.note}</Field>
          <Field label="创建于">{orphan.created_at}</Field>
        </Section>
        <Button variant="outline" size="sm" disabled={busy} onClick={() => onDeleteOverride(orphan.mal_id)}>
          删除这条 override
        </Button>
      </div>
    )
  }

  if (loading && !detail) return <div className="p-6 text-sm text-muted-foreground">加载中...</div>
  if (error && !detail) return <div className="p-6 text-sm text-destructive">{error}</div>
  if (!detail) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
        从左边选一条番组
      </div>
    )
  }

  const d = detail
  const candidates = d.candidates ?? []
  const studios = (d.mal_studios ?? []).map((s) => s.name).filter(Boolean)
  const tags = (d.bgm_tags ?? []).slice(0, 12)
  const airRange = [d.mal_start_date, d.mal_end_date].filter(Boolean).join(' ~ ')

  const submitExclude = () => {
    // other 不带说明后端会 422，就地拦住比让它跑一趟再报错好
    if (reason === 'other' && !reasonNote.trim()) {
      setLocalError('选了「其他」就得写一句说明')
      return
    }
    setLocalError(null)
    onExclude(reason, reason === 'other' ? reasonNote.trim() : null)
  }

  const submitManual = () => {
    const bgmId = parseInt(manualBgmId.trim(), 10)
    if (!bgmId || bgmId <= 0) return
    onInclude(bgmId)
  }

  const submitMove = () => {
    const bgmId = parseInt(moveBgmId, 10)
    if (!targetSeasonId || !bgmId || bgmId <= 0) return
    onMove(targetSeasonId, bgmId)
  }

  return (
    <div className={`mx-auto max-w-3xl space-y-5 p-5 ${loading ? 'opacity-60' : ''}`}>
      {/* ── 头部 ────────────────────────────────────────────────── */}
      <div className="space-y-1.5">
        <h2 className="text-lg leading-tight font-semibold">{d.mal_title_ja ?? d.mal_title}</h2>
        {d.mal_title_ja && d.mal_title !== d.mal_title_ja && (
          <p className="text-sm text-muted-foreground">{d.mal_title}</p>
        )}
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={d.status === 'included' ? 'default' : d.status === 'pending' ? 'outline' : 'secondary'}>
            {STATUS_LABELS[d.status] ?? d.status}
          </Badge>
          {d.source && <Badge variant="outline">{SOURCE_LABELS[d.source] ?? d.source}</Badge>}
          {d.origin === 'override' && <Badge variant="secondary">override 插入</Badge>}
          {d.issues.map((k) => (
            <Badge key={k} variant="destructive">
              ⚠{ISSUE_LABELS[k]}
            </Badge>
          ))}
          <span className="ml-auto text-xs text-muted-foreground">{d.updated_at?.slice(0, 19).replace('T', ' ')}</span>
        </div>
      </div>

      {(error || localError) && (
        <div className="rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">{error ?? localError}</div>
      )}

      {/* ── MAL ─────────────────────────────────────────────────── */}
      <Section
        title="MAL"
        extra={
          <a
            href={`https://myanimelist.net/anime/${d.mal_id}`}
            target="_blank"
            rel="noreferrer"
            className="font-mono text-xs text-blue-500 underline hover:text-blue-600"
          >
            {d.mal_id}
          </a>
        }
      >
        <Field label="英文名">{d.mal_title_en}</Field>
        <Field label="类型">
          {d.mal_media_type}
          {d.mal_rating !== 'general' && ` · ${d.mal_rating}`}
          {d.mal_num_episodes != null && ` · ${d.mal_num_episodes} 话`}
        </Field>
        <Field label="放送">{airRange}</Field>
        <Field label="原作">{d.mal_source && (MAL_SOURCE_LABELS[d.mal_source] ?? d.mal_source)}</Field>
        <Field label="制作">{studios.length > 0 && studios.join(' · ')}</Field>
        {!d.mal_fetched_at && (
          <p className="text-xs text-muted-foreground/70">扩展字段未回填（scripts/backfill_mal.py）</p>
        )}
        {d.mal_synopsis && <Collapsible text={d.mal_synopsis} />}
      </Section>

      {/* ── BGM ─────────────────────────────────────────────────── */}
      {d.bgm_id ? (
        <Section
          title="Bangumi"
          extra={
            <>
              <a
                href={`https://bgm.tv/subject/${d.bgm_id}`}
                target="_blank"
                rel="noreferrer"
                className="font-mono text-xs text-blue-500 underline hover:text-blue-600"
              >
                {d.bgm_id}
              </a>
              <button
                onClick={onSync}
                disabled={busy}
                className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
                title="强制刷新 BGM 数据"
              >
                ↻
              </button>
            </>
          }
        >
          {d.bgm_fetched_at == null && (
            <p className="rounded bg-amber-500/10 px-2 py-1 text-xs text-amber-600 dark:text-amber-400">
              骨架行：只有 ID，详情未拉取。点 ↻ 拉一次。
            </p>
          )}
          <Field label="原名">{d.bgm_name}</Field>
          <Field label="中文名">{d.bgm_name_cn}</Field>
          <Field label="放送">
            {d.bgm_air_date && (
              <span className={d.issues.includes('date_mismatch') ? 'font-medium text-destructive' : ''}>
                {d.bgm_air_date}
                {d.issues.includes('date_mismatch') && ' （与季度范围无交集）'}
              </span>
            )}
          </Field>
          <Field label="平台">{d.bgm_platform && `${d.bgm_platform}${d.bgm_nsfw ? ' · NSFW' : ''}`}</Field>
          {tags.length > 0 && (
            <Field label="标签">
              <span className="flex flex-wrap gap-1">
                {tags.map((t) => (
                  <Badge key={t.name} variant="secondary" className="text-[10px]">
                    {t.name}
                  </Badge>
                ))}
              </span>
            </Field>
          )}
          {d.bgm_summary && <Collapsible text={d.bgm_summary} />}
        </Section>
      ) : (
        <Section title="Bangumi">
          <p className="text-xs text-muted-foreground">未关联 BGM 条目</p>
        </Section>
      )}

      {/* ── 决策 ────────────────────────────────────────────────── */}
      <Section title="决策">
        <Field label="状态">{STATUS_LABELS[d.status] ?? d.status}</Field>
        <Field label="来源">{d.source ? (SOURCE_LABELS[d.source] ?? d.source) : '未处理'}</Field>
        <Field label="置信度">{d.confidence != null && `${(d.confidence * 100).toFixed(0)}%`}</Field>
        <Field label="排除原因">{d.reason && reasonLabel(d.reason)}</Field>
        <Field label="说明">{d.note}</Field>
        <Field label="来路">{d.origin}</Field>
        {d.error && (
          <Field label="匹配错误">
            <span className="text-destructive">{d.error}</span>
          </Field>
        )}
      </Section>

      {/* ── Override ────────────────────────────────────────────── */}
      {d.override_action && (
        <Section title="Override">
          <Field label="动作">{d.override_action}</Field>
          <Field label="bgm_id">{d.override_bgm_id}</Field>
          <Field label="原因">{d.override_reason && reasonLabel(d.override_reason)}</Field>
          <Field label="目标季">
            {d.override_target_season_id && seasonIdLabel(d.override_target_season_id)}
          </Field>
          <Field label="备注">{d.override_note}</Field>
          <Field label="创建于">{d.override_created_at}</Field>
          <Button
            variant="outline"
            size="xs"
            className="mt-1"
            disabled={busy}
            onClick={() => onDeleteOverride(d.mal_id)}
          >
            删除这条 override
          </Button>
        </Section>
      )}

      {/* ── 候选 ────────────────────────────────────────────────── */}
      {candidates.length > 0 && (
        <Section title={`候选 ${candidates.length} 条`}>
          <CandidatePanel candidates={candidates} selectedIndex={selectedCandidate} onSelect={onSelectCandidate} />
        </Section>
      )}

      {/* ── 操作 ────────────────────────────────────────────────── */}
      <Section title="操作">
        <div className="space-y-3 pt-1">
          {candidates.length > 0 && (
            <Button
              className="w-full"
              disabled={busy || selectedCandidate == null}
              onClick={() => selectedCandidate != null && onInclude(candidates[selectedCandidate].bgm_id)}
            >
              确认收录选中候选 (Enter)
            </Button>
          )}

          <div className="flex items-center gap-2">
            <Input
              type="number"
              min={1}
              placeholder="手动输入 bgm_id"
              value={manualBgmId}
              onChange={(e) => setManualBgmId(e.target.value)}
              onKeyDown={(e) => {
                e.stopPropagation()
                if (e.key === 'Enter') submitManual()
              }}
              className="w-48"
            />
            <Button
              variant="secondary"
              disabled={busy || !manualBgmId.trim() || parseInt(manualBgmId.trim(), 10) <= 0}
              onClick={submitManual}
            >
              收录此 bgm_id
            </Button>
          </div>

          <div className="space-y-2 border-t pt-3">
            <div className="flex items-baseline gap-2">
              <span className="text-xs text-muted-foreground">排除原因（可不填）</span>
              {reason && (
                <button
                  type="button"
                  onClick={() => {
                    setReason(null)
                    setReasonNote('')
                  }}
                  className="text-xs text-muted-foreground hover:underline"
                >
                  清除
                </button>
              )}
            </div>
            <ReasonPicker
              reason={reason}
              note={reasonNote}
              onChange={(r, n) => {
                setReason(r)
                setReasonNote(n)
              }}
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={busy || d.status === 'excluded'} onClick={submitExclude}>
              排除（不收录）(X)
            </Button>
            <Button variant="outline" disabled={busy || d.status === 'pending'} onClick={onPending}>
              打回待审核 (R)
            </Button>
            <Button variant="outline" disabled={busy} onClick={() => setMoveOpen((o) => !o)}>
              移至其他季度
            </Button>
          </div>

          {moveOpen && (
            <div className="space-y-3 rounded-md border bg-muted/30 p-3">
              <p className="text-sm font-medium">移至其他季度（排除当前 + 在目标季度添加 override）</p>
              <div className="flex flex-wrap items-end gap-2">
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">目标季度</label>
                  <select
                    value={targetSeasonId}
                    onChange={(e) => setTargetSeasonId(e.target.value)}
                    className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                  >
                    <option value="">选择季度...</option>
                    {seasons
                      .filter((s) => s.id !== seasonId)
                      .sort((a, b) => b.id.localeCompare(a.id))
                      .map((s) => (
                        <option key={s.id} value={s.id}>
                          {seasonIdLabel(s.id)}
                        </option>
                      ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">BGM ID</label>
                  <Input
                    type="number"
                    min={1}
                    placeholder="BGM ID"
                    value={moveBgmId}
                    onChange={(e) => setMoveBgmId(e.target.value)}
                    onKeyDown={(e) => e.stopPropagation()}
                    className="w-32"
                  />
                </div>
                <Button size="sm" disabled={busy || !targetSeasonId || !moveBgmId} onClick={submitMove}>
                  {busy ? '处理中...' : '确认移至'}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setMoveOpen(false)}>
                  取消
                </Button>
              </div>
            </div>
          )}
        </div>
      </Section>
    </div>
  )
}
