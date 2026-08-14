import type { ExcludeReason } from '@/types/api'

/**
 * 人工排除的预设原因。取值必须与 src/api/schemas.py 的 ExcludeReason 一致——
 * DB 侧刻意没加 CHECK，这两处就是全部的约束。
 *
 * wrong_season 与其余几个不是一类：它说的是「这个东西成立，但不在这一季」（位置错误），
 * 通常由「移至其他季度」自动写入，同时在源季度留一条 override skip。
 *
 * kids / mini 是「按经验排除、没去 BGM 逐条确认」，与 not_on_bgm（确认过不存在）区别开。
 */
export const EXCLUDE_REASONS: { value: ExcludeReason; label: string; hint: string }[] = [
  { value: 'not_on_bgm', label: 'BGM 未收录', hint: 'BGM 上根本没有这个条目' },
  { value: 'kids', label: '儿童向', hint: 'kids 向，BGM 大概率未收录，不逐条确认' },
  { value: 'mini', label: 'mini 动画', hint: 'YouTube 短篇 ONA，BGM 大概率未收录，不逐条确认' },
  { value: 'merged_into_ep', label: '并进本篇 ep', hint: 'BGM 没单列，算作本篇的额外话数' },
  { value: 'not_anime', label: '非动画', hint: '媒体类型不该收' },
  { value: 'duplicate', label: 'MAL 重复条目', hint: 'MAL 里同一部番的重复项' },
  { value: 'wrong_season', label: '季度标错', hint: '该去别的季度' },
  { value: 'other', label: '其他…', hint: '需要填写说明' },
]

const LABELS = new Map(EXCLUDE_REASONS.map((r) => [r.value, r.label]))

export function reasonLabel(reason: string | null | undefined): string | null {
  if (!reason) return null
  return LABELS.get(reason as ExcludeReason) ?? reason
}
