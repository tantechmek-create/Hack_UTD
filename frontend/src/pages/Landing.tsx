import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Card, DataBadge, Skeleton } from '../components/ui'
import { dayDate } from '../lib/format'

const SOURCES = [
  ['FEMA IHP registrations', 'real'],
  ['NFIP claims', 'real'],
  ['FEMA modeled damage', 'real'],
  ['NOAA Stage IV rainfall', 'real'],
  ['USGS high-water marks', 'real'],
  ['CDC Social Vulnerability Index', 'real'],
  ['Expected need · gap scores', 'predicted'],
] as const

export default function Landing() {
  const events = useQuery({ queryKey: ['events'], queryFn: api.events })
  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col justify-center gap-8 overflow-y-auto p-8">
      <div>
        <div className="text-xs font-semibold uppercase tracking-widest text-red-400">Overlooked Area Detector</div>
        <h1 className="mt-2 max-w-3xl text-4xl font-bold leading-tight">
          Find the neighborhoods the storm hit hardest that aren&apos;t asking for help.
        </h1>
        <p className="mt-3 max-w-2xl text-muted">
          For every ZIP and every day after landfall, we compare how many households <i>should</i> be asking for help
          (predicted from hazard, housing and vulnerability) with how many actually are (FEMA registrations). Hit hard
          but unusually quiet = overlooked. Public data only; no one has to reply to anything.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {!events.data && <Skeleton className="h-36" />}
        {events.error && (
          <Card className="p-4 text-sm text-red-300">
            Can&apos;t reach the API. Start it with <code>make api</code>. ({String(events.error)})
          </Card>
        )}
        {events.data?.map((e) => (
          <Card key={e.event_id} className="p-5">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-xl font-semibold">{e.name}</div>
                <div className="text-sm text-muted">
                  Landfall {dayDate(e.landfall_date, 0)} · DR-{e.disaster_number} · {e.counties}
                </div>
              </div>
              {e.data_mode === 'mock' && <DataBadge label="mock" />}
            </div>
            <Link
              to={`/event/${e.event_id}/map?day=5`}
              className="mt-4 inline-block rounded-md bg-gap px-4 py-2 text-sm font-semibold text-white hover:bg-red-500"
            >
              Open replay →
            </Link>
          </Card>
        ))}
      </div>
      <div className="flex flex-wrap gap-2 border-t border-line pt-4">
        {SOURCES.map(([s, l]) => (
          <span key={s} className="flex items-center gap-1.5 text-xs text-muted">
            {s} <DataBadge label={l} />
          </span>
        ))}
      </div>
    </div>
  )
}
