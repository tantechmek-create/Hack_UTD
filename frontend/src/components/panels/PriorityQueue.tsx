import type { PriorityItem } from '../../api/client'
import { fmtPct, fmtPred } from '../../lib/format'
import { Skeleton } from '../ui'

function toCsv(items: PriorityItem[]) {
  const head = ['rank', 'zip', 'area', 'expected_by_day', 'observed', 'gap_score', 'unmet_estimate', 'p_value', 'significant', 'svi', 'priority', 'actions']
  const rows = items.map((i) =>
    [i.rank, i.zip, `"${i.area}"`, i.expected_by_day, i.observed, i.gap_score, i.unmet_estimate, i.p_value, i.significant, i.svi, i.priority, `"${i.actions.map((a) => a.label).join('; ')}"`].join(','),
  )
  return [head.join(','), ...rows].join('\n')
}

export function PriorityQueue({
  items,
  selected,
  onPick,
  day,
}: {
  items?: PriorityItem[]
  selected?: string | null
  onPick: (it: PriorityItem) => void
  day: number
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <div>
          <div className="text-sm font-semibold">Priority queue</div>
          <div className="text-[11px] text-muted">Unmet households × vulnerability · day {day}</div>
        </div>
        <button
          disabled={!items?.length}
          onClick={() => {
            const blob = new Blob([toCsv(items ?? [])], { type: 'text/csv' })
            const a = document.createElement('a')
            a.href = URL.createObjectURL(blob)
            a.download = `priorities_day${day}.csv`
            a.click()
          }}
          className="rounded border border-line px-2 py-1 text-xs text-muted hover:text-text disabled:opacity-40"
        >
          Export CSV
        </button>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto p-2">
        {!items && [0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-20" />)}
        {items?.length === 0 && (
          <div className="p-4 text-center text-sm text-muted">No ZIPs are quieter than expected on this day.</div>
        )}
        {items?.map((it) => (
          <button
            key={it.zip}
            onClick={() => onPick(it)}
            className={`w-full rounded-lg border p-2.5 text-left transition hover:border-red-400/60 ${
              selected === it.zip ? 'border-yellow-400 bg-panel-2' : 'border-line bg-panel'
            }`}
          >
            <div className="flex items-baseline gap-2">
              <span className="num w-6 text-sm font-bold text-red-300">{it.rank}</span>
              <span className="num font-semibold">{it.zip}</span>
              <span className="truncate text-xs text-muted">{it.area}</span>
              {it.significant && (
                <span className="ml-auto rounded bg-gap/20 px-1.5 text-[10px] font-medium text-red-200">significant</span>
              )}
            </div>
            <div className="num mt-1 flex gap-4 pl-8 text-xs text-muted">
              <span>
                Unmet <b className="text-text">{fmtPred(it.unmet_estimate)}</b>
              </span>
              <span>
                Quiet <b className="text-text">{fmtPct(it.gap_score)}</b>
              </span>
              <span>
                SVI <b className="text-text">{it.svi?.toFixed(2)}</b>
              </span>
            </div>
            <div className="mt-1.5 flex flex-wrap gap-1 pl-8">
              {it.actions.map((a, i) => (
                <span
                  key={a.code}
                  title={a.why}
                  className={`rounded px-1.5 py-0.5 text-[10px] ${i === 0 ? 'bg-red-500/20 text-red-100' : 'bg-panel-2 text-muted'}`}
                >
                  {a.label}
                </span>
              ))}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
