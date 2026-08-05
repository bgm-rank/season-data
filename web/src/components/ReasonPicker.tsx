import { Input } from '@/components/ui/input'
import { EXCLUDE_REASONS } from '@/lib/reasons'
import type { ExcludeReason } from '@/types/api'

interface Props {
  reason: ExcludeReason | null
  note: string
  onChange: (reason: ExcludeReason | null, note: string) => void
}

/**
 * 排除原因选择器：一排单选 chip，再点一次取消。
 *
 * **不填也能提交**——常见情况零成本，长尾才付文字代价，否则审核会慢到没人愿意填。
 * 唯一的例外是「其他…」，不带说明就没有信息量，后端也会 422。
 */
export function ReasonPicker({ reason, note, onChange }: Props) {
  return (
    <div className="space-y-2">
      <div className="flex gap-1.5 flex-wrap">
        {EXCLUDE_REASONS.map((r) => (
          <button
            key={r.value}
            type="button"
            title={r.hint}
            onClick={() => onChange(reason === r.value ? null : r.value, r.value === 'other' ? note : '')}
            className={`px-2 py-1 rounded-full border text-xs transition-colors ${
              reason === r.value
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-input hover:bg-muted text-muted-foreground'
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>
      {reason === 'other' && (
        <Input
          autoFocus
          placeholder="说明（必填）"
          value={note}
          onChange={(e) => onChange(reason, e.target.value)}
          onKeyDown={(e) => e.stopPropagation()}
          className="h-8 text-sm"
        />
      )}
    </div>
  )
}
