import type { Kpis } from '../../api/client'
import { fmtInt, fmtPred } from '../../lib/format'
import { DataBadge, Skeleton } from '../ui'

export function KpiStrip({ k }: { k?: Kpis }) {
  if (!k)
    return (
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-16" />)}
      </div>
    )
  const tiles = [
    { label: 'Households expected to need help', value: fmtPred(k.expected_final), badge: 'predicted' as const },
    { label: 'Registered so far', value: fmtInt(k.registered), badge: 'real' as const, src: 'FEMA' },
    {
      label: 'Estimated unmet (significant ZIPs)',
      value: k.too_early ? 'Too early' : fmtPred(k.unmet),
      badge: 'predicted' as const,
      accent: !k.too_early,
    },
    {
      label: 'ZIPs significantly quiet',
      value: k.too_early ? '—' : `${k.n_significant} / ${k.n_zips}`,
      badge: 'predicted' as const,
      accent: !k.too_early,
    },
  ]
  return (
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-lg border border-line bg-panel px-3 py-2">
          <div className="flex items-start justify-between gap-2">
            <span className="text-[11px] leading-tight text-muted">{t.label}</span>
            <DataBadge label={t.badge} source={t.src} />
          </div>
          <div className={`num mt-1 text-xl font-semibold ${t.accent ? 'text-red-300' : ''}`}>{t.value}</div>
        </div>
      ))}
    </div>
  )
}
