import type { SeasonName } from '@/types/api'

/**
 * 季度显示统一带上起始月份：日漫的 winter 是一年的开始（1 月），
 * 只写「冬」很反直觉，加上月份数字才能一眼看出先后顺序。
 */
export const SEASONS: { value: SeasonName; month: number; cn: string; en: string }[] = [
  { value: 'winter', month: 1, cn: '冬', en: 'Winter' },
  { value: 'spring', month: 4, cn: '春', en: 'Spring' },
  { value: 'summer', month: 7, cn: '夏', en: 'Summer' },
  { value: 'fall', month: 10, cn: '秋', en: 'Fall' },
]

const BY_VALUE = new Map(SEASONS.map((s) => [s.value, s]))

/** 列表/标题用的短标签，如 `冬 (1月)`；未知取值原样返回 */
export function seasonLabel(season: string): string {
  const s = BY_VALUE.get(season as SeasonName)
  return s ? `${s.cn} (${s.month}月)` : season
}

/** 表单选项用的长标签，如 `冬 Winter (1月)` */
export function seasonOptionLabel(season: SeasonName): string {
  const s = BY_VALUE.get(season)
  return s ? `${s.cn} ${s.en} (${s.month}月)` : season
}

/** season_id（`2026-winter`）→ `2026 冬 (1月)`；解析不出来就原样返回 */
export function seasonIdLabel(seasonId: string): string {
  const [year, name] = seasonId.split('-')
  const s = name ? BY_VALUE.get(name as SeasonName) : undefined
  return s ? `${year} ${s.cn} (${s.month}月)` : seasonId
}
