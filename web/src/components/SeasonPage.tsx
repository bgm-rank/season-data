import { useState } from 'react'
import { SeasonList } from '@/components/SeasonList'
import { SeasonForm } from '@/components/SeasonForm'

export function SeasonPage() {
  const [refreshSignal, setRefreshSignal] = useState(0)

  return (
    <div className="space-y-8">
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">新建季度</h2>
        <SeasonForm onCreated={() => setRefreshSignal((n) => n + 1)} />
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">季度列表</h2>
        <SeasonList refreshSignal={refreshSignal} />
      </section>
    </div>
  )
}
