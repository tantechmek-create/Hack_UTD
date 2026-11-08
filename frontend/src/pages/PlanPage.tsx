import { useMutation } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api } from '../api/client'
import { LAYERS } from '../components/map/layers'
import { ZipMap } from '../components/map/ZipMap'
import { Card, DataBadge, Toggle } from '../components/ui'
import { useEventState, useMapDay } from '../hooks/useEventState'
import { fmtPct, fmtPred } from '../lib/format'

export default function PlanPage() {
  const { eventId, day, event } = useEventState()
  const [k, setK] = useState(4)
  const [radius, setRadius] = useState(10)
  const [exclude, setExclude] = useState(true)
  const map = useMapDay(eventId, day)
  const plan = useMutation({
    mutationFn: () => api.plan(eventId, { day, k, radius_km: radius, exclude_flooded: exclude }),
  })
  const sites = useMemo(
    () => plan.data?.sites.map((s) => ({ id: s.site_id, name: s.name, lat: s.lat, lon: s.lon, radius_km: plan.data!.radius_km })),
    [plan.data],
  )

  return (
    <div className="flex h-full">
      <div className="flex w-[380px] shrink-0 flex-col gap-3 overflow-y-auto border-r border-line p-4">
        <div>
          <h2 className="text-lg font-semibold">Plan deployment</h2>
          <p className="text-xs text-muted">
            Picks the {k} sites that put the most priority-weighted unmet households within {radius} km, using the day {day} ranking.
            Greedy max-coverage: guaranteed within ~63% of optimal.
          </p>
        </div>
        <Card className="space-y-3 p-3 text-sm">
          <label className="block">
            <div className="flex justify-between"><span>Teams (k)</span><b className="num">{k}</b></div>
            <input type="range" min={1} max={10} value={k} onChange={(e) => setK(+e.target.value)} className="w-full" />
          </label>
          <label className="block">
            <div className="flex justify-between"><span>Coverage radius</span><b className="num">{radius} km</b></div>
            <input type="range" min={5} max={15} value={radius} onChange={(e) => setRadius(+e.target.value)} className="w-full" />
          </label>
          <div className="flex items-center justify-between">
            <Toggle on={exclude} onChange={setExclude} label="Exclude flooded sites" />
            <button
              onClick={() => plan.mutate()}
              className="rounded-md bg-gap px-4 py-1.5 text-sm font-semibold text-white hover:bg-red-500"
            >
              {plan.isPending ? 'Running…' : 'Run'}
            </button>
          </div>
        </Card>

        {plan.error && <div className="text-xs text-red-300">{String(plan.error)}</div>}
        {plan.data && (
          <>
            <Card className="p-3">
              <div className="text-xs text-muted">Priority need within reach</div>
              <div className="num text-3xl font-bold text-yellow-300">{fmtPct(plan.data.coverage_pct)}</div>
              <div className="h-2 rounded bg-panel-2">
                <div className="h-full rounded bg-yellow-400" style={{ width: fmtPct(plan.data.coverage_pct) }} />
              </div>
              <div className="num mt-1 text-xs text-muted">
                {fmtPred(plan.data.households_covered)} unmet households · {plan.data.sites_excluded_flooded} flooded sites excluded
              </div>
            </Card>
            <div className="space-y-2">
              {plan.data.sites.map((s, i) => (
                <Card key={s.site_id} className="p-2.5 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-yellow-400 text-[11px] font-bold text-ink">{i + 1}</span>
                    <span className="font-medium">{s.name}</span>
                    <span className="ml-auto"><DataBadge label={s.source === 'simulated' ? 'simulated' : 'real'} source={s.source === 'simulated' ? undefined : s.source.split(' ')[0]} /></span>
                  </div>
                  <div className="num mt-1 pl-7 text-xs text-muted">
                    {s.kind.replace(/_/g, ' ')} · {s.covered_zips.length} ZIPs · {fmtPred(s.households_covered)} households
                  </div>
                  <div className="pl-7 text-[11px] text-muted">Top: {s.top_zips.map((z) => z.zip).join(', ')}</div>
                </Card>
              ))}
            </div>
          </>
        )}
        {!plan.data && (
          <p className="text-xs text-muted">
            Run the optimizer to place teams. Candidates are public schools (NCES); sites near deep high-water marks count as flooded.
          </p>
        )}
      </div>
      <div className="relative flex-1">
        <ZipMap data={map.data} fillColor={LAYERS.gap.color} bbox={event?.bbox} sites={sites} />
      </div>
    </div>
  )
}
