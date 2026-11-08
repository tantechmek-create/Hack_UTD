import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { api, type ZipProps } from '../api/client'
import { DaySlider } from '../components/controls/DaySlider'
import { LAYERS, type LayerKey } from '../components/map/layers'
import { ZipMap } from '../components/map/ZipMap'
import { KpiStrip } from '../components/panels/KpiStrip'
import { PriorityQueue } from '../components/panels/PriorityQueue'
import { ZipDetail } from '../components/panels/ZipDetail'
import { Toggle } from '../components/ui'
import { useEventState, useKpis, useMapDay, usePriorities } from '../hooks/useEventState'
import { fmtInt, fmtPct, fmtPred } from '../lib/format'

function tooltip(p: ZipProps) {
  const gap =
    p.expected_by_day != null
      ? `Expected ${fmtPred(p.expected_by_day)} · Observed ${fmtInt(p.observed)} · <b>${fmtPct(p.gap_score)} quiet</b>${
          p.significant ? ' · <span style="color:#fca5a5">significant</span>' : ''
        }`
      : 'No registrations scored yet'
  return `<div style="font-weight:600">${p.zip} <span style="color:#8b98a8;font-weight:400">${p.area}</span></div>
    <div>${gap}</div>
    <div style="color:#8b98a8">Rain ${p.rain_in ?? '—'} in · SVI ${p.svi?.toFixed(2) ?? '—'}</div>`
}

export default function MapDashboard() {
  const { eventId, day, zip, event, setDay, setZip } = useEventState()
  const [layer, setLayer] = useState<LayerKey>(day <= 1 ? 'hazard' : 'gap')
  const [sigOnly, setSigOnly] = useState(false)
  const [fly, setFly] = useState<{ lon: number; lat: number; key: number } | null>(null)
  const qc = useQueryClient()

  const map = useMapDay(eventId, day)
  const kpis = useKpis(eventId, day)
  const pr = usePriorities(eventId, day, sigOnly)

  const prefetch = useCallback(
    (d: number) => {
      if (!event || d < 0 || d > event.max_day) return
      qc.prefetchQuery({ queryKey: ['map', eventId, d], queryFn: () => api.map(eventId, d), staleTime: Infinity })
      qc.prefetchQuery({ queryKey: ['kpis', eventId, d], queryFn: () => api.kpis(eventId, d), staleTime: Infinity })
    },
    [qc, eventId, event],
  )

  const data = useMemo(() => {
    if (!map.data || !sigOnly) return map.data
    return { ...map.data, features: map.data.features.filter((f) => f.properties.significant) }
  }, [map.data, sigOnly])

  const def = LAYERS[layer]

  return (
    <div className="flex h-full flex-col">
      {/* top bar */}
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-panel px-4 py-2">
        <div className="mr-2">
          <div className="text-sm font-semibold">{event?.name ?? '…'}</div>
          <div className="text-[11px] text-muted">DR-{event?.disaster_number} · {event?.counties}</div>
        </div>
        {event && <DaySlider day={day} maxDay={event.max_day} landfall={event.landfall_date} onChange={setDay} onPrefetch={prefetch} />}
        <div className="flex overflow-hidden rounded-md border border-line">
          {(Object.keys(LAYERS) as LayerKey[]).map((k) => (
            <button
              key={k}
              onClick={() => setLayer(k)}
              className={`px-3 py-1.5 text-xs ${layer === k ? 'bg-panel-2 font-semibold text-text' : 'text-muted hover:text-text'}`}
            >
              {LAYERS[k].label}
            </button>
          ))}
        </div>
        <Toggle on={sigOnly} onChange={setSigOnly} label="Significant only" />
      </div>

      <div className="px-4 py-2">
        <KpiStrip k={kpis.data} />
      </div>

      <div className="flex min-h-0 flex-1 gap-0 border-t border-line">
        <div className="relative min-w-0 flex-[65]">
          <ZipMap
            data={data}
            fillColor={def.color}
            bbox={event?.bbox}
            selectedZip={zip}
            flyTo={fly}
            outlineSignificant={layer === 'gap'}
            tooltip={tooltip}
            onSelect={(z) => setZip(z)}
          />
          {/* legend */}
          <div className="pointer-events-none absolute bottom-6 left-3 rounded-md border border-line bg-panel/90 px-3 py-2 text-[11px]">
            <div className="mb-1 text-muted">{def.legend.label}</div>
            <div className="flex">
              {def.legend.stops.map((c) => <div key={c} className="h-2 w-10" style={{ background: c }} />)}
            </div>
            <div className="flex justify-between text-muted">
              {def.legend.ticks.map((t) => <span key={t}>{t}</span>)}
            </div>
            {layer === 'gap' && <div className="mt-1 text-muted"><span className="text-red-200">▭</span> outline = statistically significant</div>}
          </div>
          {kpis.data?.too_early && layer === 'gap' && (
            <div className="absolute left-1/2 top-3 -translate-x-1/2 rounded-md border border-line bg-panel/95 px-3 py-1.5 text-xs text-muted">
              Too early for a gap signal: few people have registered yet. The Hazard layer is the better view on day {day}.
            </div>
          )}
        </div>
        <div className="min-w-[320px] flex-[35] border-l border-line bg-ink">
          {zip ? (
            <ZipDetail eventId={eventId} zip={zip} day={day} onClose={() => setZip(null)} />
          ) : (
            <PriorityQueue
              items={pr.data?.items}
              day={day}
              selected={zip}
              onPick={(it) => {
                setFly({ lon: it.lon, lat: it.lat, key: Date.now() })
                setZip(it.zip)
              }}
            />
          )}
        </div>
      </div>
    </div>
  )
}
