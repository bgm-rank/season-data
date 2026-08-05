import { Badge } from '@/components/ui/badge'
import type { IssueKind, Item, ItemStatus, Override } from '@/types/api'

/**
 * 左列的一行。
 *
 * 'orphan' 是建了 add override 但还没跑 run 的待办——它在 overrides 表里有行、
 * 在 season_items 里没有，所以拿不到 status/候选，只能靠 override 自己的字段渲染。
 * 详情路由对这种 mal_id 会 404，右侧面板必须走另一个分支。
 */
export type BoardRow =
  | { kind: 'item'; malId: number; item: Item }
  | { kind: 'orphan'; malId: number; override: Override }

export const ISSUE_LABELS: Record<IssueKind, string> = {
  dup_in_season: '季内重复',
  dup_global: '跨季重复',
  date_mismatch: '日期不符',
  no_bgm_name: '无 BGM 名',
}

export const SOURCE_LABELS: Record<string, string> = {
  rule: '规则排除',
  exact: '精确匹配',
  llm: 'LLM',
  human: '人工',
}

/** 单字缩写，左列窄、放不下全称，全称留给右侧详情 */
const SOURCE_ABBR: Record<string, string> = {
  rule: '规',
  exact: '精',
  llm: 'L',
  human: '人',
}

const STATUS_BAR: Record<ItemStatus, string> = {
  pending: 'bg-amber-500',
  included: 'bg-emerald-500',
  excluded: 'bg-muted-foreground/25',
}

interface Props {
  row: BoardRow
  selected: boolean
  busy: boolean
  error: string | null
  onSelect: () => void
  onExclude: () => void
  onPending: () => void
  onSync: () => void
}

/** 第二行：这条番当前匹配到了什么。没匹配上就说清楚卡在哪一步。 */
function SecondLine({ item }: { item: Item }) {
  if (item.bgm_id) {
    return (
      <>
        <span className="truncate">{item.bgm_name ?? item.bgm_name_cn ?? `bgm:${item.bgm_id}`}</span>
        {item.bgm_air_date && (
          <span
            className={`shrink-0 tabular-nums ${
              item.issues.includes('date_mismatch') ? 'text-destructive font-medium' : ''
            }`}
          >
            {item.bgm_air_date.slice(0, 7)}
          </span>
        )}
        {item.confidence != null && (
          <span className="shrink-0 tabular-nums">{Math.round(item.confidence * 100)}%</span>
        )}
      </>
    )
  }
  if (item.candidates?.length) {
    return <span className="truncate">候选 {item.candidates.length} 条待选</span>
  }
  if (item.error) {
    return <span className="truncate text-destructive">{item.error}</span>
  }
  return <span className="truncate opacity-60">未匹配</span>
}

export function ItemRow({ row, selected, busy, error, onSelect, onExclude, onPending, onSync }: Props) {
  const orphan = row.kind === 'orphan'
  const item = row.kind === 'item' ? row.item : null
  const title = orphan
    ? (row.override.mal_title ?? `mal:${row.malId}`)
    : (item!.mal_title_ja ?? item!.mal_title)

  return (
    <div
      role="option"
      aria-selected={selected}
      onClick={onSelect}
      className={`group flex cursor-pointer items-stretch gap-2 rounded border px-1.5 py-1 text-xs transition-colors ${
        selected ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'border-transparent hover:bg-muted/50'
      } ${orphan ? 'border-dashed !border-muted-foreground/40' : ''} ${busy ? 'opacity-50' : ''}`}
    >
      <span
        className={`w-0.5 shrink-0 rounded-full ${orphan ? 'bg-blue-500' : STATUS_BAR[item!.status]}`}
        aria-hidden
      />

      <div className="min-w-0 flex-1 leading-snug">
        <div className="flex items-baseline gap-1.5">
          <span className="shrink-0 font-mono text-muted-foreground/60 tabular-nums">{row.malId}</span>
          <span className="truncate font-medium">{title}</span>
        </div>
        <div className="flex items-baseline gap-1.5 pl-1 text-muted-foreground">
          <span className="shrink-0 opacity-40">→</span>
          {orphan ? (
            <span className="truncate">
              override {row.override.action}
              {row.override.bgm_id ? ` · bgm:${row.override.bgm_id}` : ' · bgm_id 待查'}
            </span>
          ) : (
            <SecondLine item={item!} />
          )}
        </div>
        {error && <div className="pl-1 text-destructive">{error}</div>}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        {orphan && (
          <Badge variant="outline" className="text-[10px]">
            待 run
          </Badge>
        )}
        {item?.issues.map((k) => (
          <span key={k} className="text-destructive" title={ISSUE_LABELS[k]}>
            ⚠
          </span>
        ))}
        {item?.override_action && (
          <span className="text-blue-500" title={`override ${item.override_action}`}>
            ◆
          </span>
        )}
        {item?.source && (
          <span className="text-muted-foreground/50" title={SOURCE_LABELS[item.source] ?? item.source}>
            {SOURCE_ABBR[item.source] ?? item.source}
          </span>
        )}

        {/* 行内快捷操作：hover 或选中才出现，避免每行都挂三个图标把列表搅浑 */}
        <span
          className={`flex items-center gap-1 ${selected ? '' : 'opacity-0 group-hover:opacity-100'}`}
          onClick={(e) => e.stopPropagation()}
        >
          {item?.bgm_id && (
            <button
              onClick={onSync}
              disabled={busy}
              className="text-muted-foreground hover:text-foreground disabled:opacity-40"
              title="强制刷新 BGM 数据"
            >
              ↻
            </button>
          )}
          {item && item.status !== 'excluded' && (
            <button
              onClick={onExclude}
              disabled={busy}
              className="text-muted-foreground hover:text-destructive disabled:opacity-40"
              title="排除（快捷键 x）"
            >
              ✗
            </button>
          )}
          {item && item.status !== 'pending' && (
            <button
              onClick={onPending}
              disabled={busy}
              className="text-muted-foreground hover:text-foreground disabled:opacity-40"
              title="打回待审核（快捷键 r）"
            >
              ↺
            </button>
          )}
        </span>
      </div>
    </div>
  )
}
