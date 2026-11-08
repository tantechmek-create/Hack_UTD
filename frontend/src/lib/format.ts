export const fmtInt = (n: number | null | undefined) =>
  n == null || Number.isNaN(n) ? '—' : Math.round(n).toLocaleString('en-US')

/** Predictions get a "~" so nobody mistakes them for counts. */
export const fmtPred = (n: number | null | undefined) => (n == null ? '—' : `~${fmtInt(n)}`)

export const fmtPct = (x: number | null | undefined, digits = 0) =>
  x == null ? '—' : `${(x * 100).toFixed(digits)}%`

export const fmtP = (p: number) => (p < 0.001 ? 'p < 0.001' : `p = ${p.toFixed(3)}`)

export function dayDate(landfall: string, day: number) {
  const d = new Date(`${landfall}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + day)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
}

export const FEATURE_NAMES: Record<string, string> = {
  rain_total_in: 'Storm rainfall',
  rain_sq: 'Rainfall (extreme)',
  damage_pts_per_1k_hu: 'Modeled damaged buildings',
  hwm_max_ft: 'High-water mark height',
  hwm_count: 'High-water marks',
  hist_nfip_claims_per_1k_hu: 'Past flood claims',
  nri_flood_eal_score: 'Baseline flood risk',
  pct_mobile: 'Mobile homes',
  pct_poverty: 'Poverty',
  pct_noveh: 'No vehicle',
  pct_65plus: 'Age 65+',
  pct_limeng: 'Limited English',
}

export const featureName = (k: string) => FEATURE_NAMES[k] ?? k.replace(/_/g, ' ')
