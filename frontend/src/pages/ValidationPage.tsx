import { useQuery } from '@tanstack/react-query'
import type { ExpressionSpecification } from 'maplibre-gl'
import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { ZipMap } from '../components/map/ZipMap'
import { Card, DataBadge, Skeleton } from '../components/ui'
import { useEventState, useMapDay } from '../hooks/useEventState'

const METHODS: Record<string, { label: string; color: string }> = {
  ours: { label: 'Our gap ranking', color: '#ef4444' },
  housing_pace: { label: 'Gap vs. housing units', color: '#eab308' },
  rainfall_only: { label: 'Rainfall only', color: '#3b82f6' },
  svi_only: { label: 'SVI only', color: '#8b5cf6' },
  raw_registrations: { label: 'Fewest registrations', color: '#64748b' },
}

const OUTCOME_COLOR = [
  'match',
  ['get', 'bt'],
  'tp', '#22c55e',
  'miss', '#64748b',
  'fa', '#f97316',
  '#161d26',
] as unknown as ExpressionSpecification

export default function ValidationPage() {
  const { eventId, event } = useEventState()
  const [k, setK] = useState(10)
  const bt = useQuery({ queryKey: ['backtest', eventId], queryFn: () => api.backtest(eventId) })
  const map = useMapDay(eventId, 5)

  const chart = useMemo(() => {
    if (!bt.data) return []
    const days = [...new Set(bt.data.metrics.map((m) => m.day))]
    return days.map((d) => {
      const row: Record<string, number | string> = { day: `Day ${d}` }
      for (const m of bt.data.metrics.filter((x) => x.day === d && x.k === k)) row[m.method] = m.precision
      return row
    })
  }, [bt.data, k])

  const tiles = useMemo(
    () => bt.data?.metrics.filter((m) => m.method === 'ours').sort((a, b) => a.k - b.k || a.day - b.day) ?? [],
    [bt.data],
  )

  const outcomeMap = useMemo(() => {
    if (!map.data || !bt.data) return undefined
    const top = new Set(bt.data.top25_day5)
    return {
      ...map.data,
      features: map.data.features.map((f) => {
        const truth = bt.data.labels[f.properties.zip]
        const flagged = top.has(f.properties.zip)
        const v = flagged && truth ? 'tp' : truth ? 'miss' : flagged ? 'fa' : 'none'
        return { ...f, properties: { ...f.properties, bt: v } }
      }),
    }
  }, [map.data, bt.data])

  const day5 = bt.data?.metrics.filter((m) => m.day === 5 && m.k === 10)
  const ours5 = day5?.find((m) => m.method === 'ours')
  // compare with the strongest baseline, not the weakest
  const best5 = day5?.filter((m) => m.method !== 'ours').sort((a, b) => b.hits - a.hits)[0]

  return (
    <div className="flex h-full">
      <div className="flex w-[460px] shrink-0 flex-col gap-3 overflow-y-auto border-r border-line p-4">
        <div>
          <h2 className="text-lg font-semibold">What we would have caught</h2>
          <p className="text-xs text-muted">{bt.data?.definition}</p>
        </div>
        {ours5 && best5 && (
          <Card className="border-gap/40 p-3 text-sm">
            At day 5, <b className="text-red-300">{ours5.hits} of our top 10</b> were among the {ours5.n_true} most overlooked ZIPs;
            the best baseline ({METHODS[best5.method]?.label.toLowerCase() ?? best5.method}) found <b>{best5.hits}</b>.{' '}
            {event?.data_mode === 'mock' && <span className="text-sim">(Mock data: illustrative only.)</span>}
          </Card>
        )}
        <div className="grid grid-cols-3 gap-2">
          {!bt.data && [0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-16" />)}
          {tiles.map((m) => (
            <Card key={`${m.k}-${m.day}`} className="p-2">
              <div className="text-[10px] text-muted">Precision@{m.k} · day {m.day}</div>
              <div className="num text-xl font-semibold">{(m.precision * 100).toFixed(0)}%</div>
            </Card>
          ))}
        </div>
        <Card className="p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">Precision@{k} vs single-signal baselines</span>
            <div className="flex overflow-hidden rounded border border-line text-xs">
              {[10, 25].map((v) => (
                <button key={v} onClick={() => setK(v)} className={`px-2 py-0.5 ${k === v ? 'bg-panel-2' : 'text-muted'}`}>
                  @{v}
                </button>
              ))}
            </div>
          </div>
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={chart} margin={{ left: -16, right: 4 }}>
                <CartesianGrid stroke="#263140" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" tick={{ fill: '#8b98a8', fontSize: 11 }} />
                <YAxis domain={[0, 1]} tickFormatter={(v) => `${v * 100}%`} tick={{ fill: '#8b98a8', fontSize: 10 }} />
                <Tooltip
                  contentStyle={{ background: '#121820', border: '1px solid #263140', fontSize: 12 }}
                  formatter={(v, n) => [`${(Number(v) * 100).toFixed(0)}%`, METHODS[String(n)]?.label ?? n]}
                />
                <Legend formatter={(v) => <span className="text-xs text-muted">{METHODS[v]?.label ?? v}</span>} />
                {Object.entries(METHODS).map(([key, m]) => (
                  <Bar key={key} dataKey={key} fill={m.color} radius={[2, 2, 0, 0]} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <div className="flex flex-wrap gap-3 text-xs text-muted">
          <span><span className="text-green-500">■</span> Flagged and truly overlooked</span>
          <span><span className="text-slate-500">■</span> Overlooked, missed</span>
          <span><span className="text-orange-500">■</span> Flagged, not overlooked</span>
        </div>
        <div className="text-[11px] text-muted">
          Outcome <DataBadge label="real" /> vs ranking <DataBadge label="predicted" /> · map shows our day-5 top 25.
        </div>
      </div>
      <div className="relative flex-1">
        <ZipMap data={outcomeMap} fillColor={OUTCOME_COLOR} bbox={event?.bbox} outlineSignificant={false} />
      </div>
    </div>
  )
}
