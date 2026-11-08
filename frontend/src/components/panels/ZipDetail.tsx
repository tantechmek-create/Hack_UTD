import { useQuery } from '@tanstack/react-query'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../../api/client'
import { featureName, fmtInt, fmtP, fmtPct, fmtPred } from '../../lib/format'
import { DataBadge, Skeleton } from '../ui'

const STATUS = {
  flagged: { text: 'Significantly quiet', cls: 'bg-gap/20 text-red-200 border-gap/50' },
  watch: { text: 'Quieter than expected', cls: 'bg-orange-500/10 text-orange-200 border-orange-500/40' },
  on_pace: { text: 'On pace', cls: 'bg-real/10 text-green-200 border-real/40' },
}

export function ZipDetail({
  eventId,
  zip,
  day,
  onClose,
}: {
  eventId: string
  zip: string
  day: number
  onClose: () => void
}) {
  const q = useQuery({
    queryKey: ['zip', eventId, zip, day],
    queryFn: () => api.zip(eventId, zip, day),
    placeholderData: (prev) => (prev?.zip === zip ? prev : undefined),
  })
  const d = q.data

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between border-b border-line px-3 py-2">
        <div>
          <div className="num text-lg font-semibold">{zip}</div>
          <div className="text-xs text-muted">{d?.area ?? ' '}</div>
        </div>
        <div className="flex items-center gap-2">
          {d?.gap && (
            <span className={`rounded border px-2 py-0.5 text-[11px] ${STATUS[d.gap.status].cls}`}>
              {STATUS[d.gap.status].text}
            </span>
          )}
          <button onClick={onClose} className="rounded px-2 text-lg leading-none text-muted hover:text-text" aria-label="Close">
            ×
          </button>
        </div>
      </div>

      {!d ? (
        <div className="space-y-2 p-3">
          <Skeleton className="h-40" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ) : (
        <div className="flex-1 space-y-4 overflow-y-auto p-3 text-sm">
          {d.gap && (
            <div className="num grid grid-cols-3 gap-2 text-center">
              <Stat label="Expected so far" value={fmtPred(d.gap.expected_by_day)} badge="predicted" />
              <Stat label="Observed" value={fmtInt(d.gap.observed)} badge="real" />
              <Stat label="Unmet (est.)" value={fmtPred(d.gap.unmet_estimate)} badge="predicted" accent />
            </div>
          )}

          <section>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Registrations vs expected</h4>
            <div className="h-40">
              <ResponsiveContainer>
                <LineChart data={d.series} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
                  <CartesianGrid stroke="#263140" strokeDasharray="3 3" />
                  <XAxis dataKey="day" tick={{ fill: '#8b98a8', fontSize: 10 }} />
                  <YAxis tick={{ fill: '#8b98a8', fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ background: '#121820', border: '1px solid #263140', fontSize: 12 }}
                    formatter={(v, n) => [fmtInt(Number(v)), n === 'expected' ? 'Expected (pace-adjusted)' : 'Observed']}
                    labelFormatter={(l) => `Day ${l}`}
                  />
                  <ReferenceLine x={day} stroke="#facc15" strokeDasharray="4 2" />
                  <Line type="monotone" dataKey="expected" stroke="#a78bfa" strokeDasharray="5 3" dot={false} strokeWidth={2} />
                  <Line type="monotone" dataKey="observed" stroke="#ef4444" dot={false} strokeWidth={2.5} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="flex gap-3 text-[11px] text-muted">
              <span><span className="text-red-400">━</span> Observed (Real)</span>
              <span><span className="text-violet-400">┅</span> Expected (Predicted)</span>
              {d.gap && <span className="ml-auto">{fmtP(d.gap.p_value)}</span>}
            </div>
            {d.flag_history.first_flagged_day != null && (
              <div className="mt-1 text-[11px] text-muted">
                Flagged from day {d.flag_history.first_flagged_day}
                {d.flag_history.resolved ? `; resolved after day ${d.flag_history.last_flagged_day}` : ''}
              </div>
            )}
          </section>

          <section>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Why flagged</h4>
            <ul className="space-y-1">
              {d.reasons.map((r) => (
                <li key={r.text} className="flex items-start justify-between gap-2">
                  <span>{r.text}</span>
                  <DataBadge label={r.label} />
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Recommended actions</h4>
            <div className="space-y-1">
              {d.actions.map((a, i) => (
                <div key={a.code} className={`rounded border px-2 py-1 ${i === 0 ? 'border-gap/50 bg-gap/10' : 'border-line'}`}>
                  <div className="font-medium">{a.label}</div>
                  <div className="text-[11px] text-muted">{a.why}</div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h4 className="mb-1 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-muted">
              Who lives here <DataBadge label="real" source="CDC SVI" />
            </h4>
            <div className="space-y-1.5">
              {d.vulnerability.map((v) => (
                <div key={v.key}>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-muted">% {v.label.replace(/^(of |speak |live |residents )/, '')}</span>
                    <span className={`num ${v.high ? 'font-semibold text-red-300' : ''}`}>
                      {fmtPct(v.value)} <span className="text-muted">(median {fmtPct(v.median)})</span>
                    </span>
                  </div>
                  <div className="relative h-1.5 rounded bg-panel-2">
                    <div
                      className={`h-full rounded ${v.high ? 'bg-red-400' : 'bg-slate-500'}`}
                      style={{ width: `${Math.min(100, (v.value / Math.max(v.p75 * 1.8, 0.01)) * 100)}%` }}
                    />
                    <div className="absolute top-[-2px] h-2.5 w-px bg-text/70" style={{ left: `${Math.min(100, (v.median / Math.max(v.p75 * 1.8, 0.01)) * 100)}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h4 className="mb-1 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-muted">
              What drives the expected need <DataBadge label="predicted" />
            </h4>
            <div className="mb-1 text-[11px] text-muted">
              {fmtPred(d.prediction.expected_final)} households (80%: {fmtInt(d.prediction.lo80)}–{fmtInt(d.prediction.hi80)}) ·{' '}
              {d.prediction.model_version}
            </div>
            <div className="space-y-1">
              {d.prediction.contributions.slice(0, 6).map((c) => {
                const w = Math.min(50, Math.abs(c.value) * 25)
                return (
                  <div key={c.feature} className="flex items-center gap-2 text-[11px]">
                    <span className="w-36 shrink-0 truncate text-muted">{featureName(c.feature)}</span>
                    <div className="relative h-2 flex-1">
                      <div className="absolute left-1/2 h-full w-px bg-line" />
                      <div
                        className={`absolute h-full rounded ${c.value >= 0 ? 'bg-amber-500' : 'bg-sky-600'}`}
                        style={c.value >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          </section>

          <section className="num grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
            <span className="text-muted">Storm rainfall</span><span>{d.hazard.rain_total_in ?? '—'} in</span>
            <span className="text-muted">High-water marks</span><span>{d.hazard.hwm_count ?? 0} (max {d.hazard.hwm_max_ft ?? 0} ft)</span>
            {d.hazard.damage_pts_per_1k_hu != null && (
              <>
                <span className="text-muted">Modeled damage</span><span>{d.hazard.damage_pts_per_1k_hu} per 1k homes</span>
              </>
            )}
            <span className="text-muted">Housing units</span><span>{fmtInt(d.housing_units)}</span>
          </section>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, badge, accent }: { label: string; value: string; badge: 'real' | 'predicted'; accent?: boolean }) {
  return (
    <div className="rounded border border-line bg-panel-2 px-1 py-1.5">
      <div className="text-[10px] text-muted">{label}</div>
      <div className={`text-base font-semibold ${accent ? 'text-red-300' : ''}`}>{value}</div>
      <DataBadge label={badge} />
    </div>
  )
}
