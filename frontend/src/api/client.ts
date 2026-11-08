// The single place API URLs are defined; components never call fetch directly.

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api'

export type DataLabel = 'real' | 'predicted' | 'simulated'

export interface EventInfo {
  event_id: string
  name: string
  disaster_number: number
  landfall_date: string
  bbox: [number, number, number, number]
  center: [number, number]
  max_day: number
  data_mode: 'mock' | 'real'
  counties?: string
}

export interface ZipProps {
  zip: string
  area: string
  housing_units: number
  svi: number | null
  rain_in: number | null
  hazard_index: number | null
  expected_final: number | null
  expected_by_day: number | null
  observed: number | null
  gap_score: number | null
  unmet: number | null
  significant: boolean
  priority: number | null
  rank: number | null
  lead_action: string | null
  [k: string]: unknown
}

export interface ZipFeatureCollection {
  type: 'FeatureCollection'
  features: { type: 'Feature'; id: string; geometry: GeoJSON.Geometry; properties: ZipProps }[]
}

export interface Kpis {
  day: number
  date: string
  expected_final: number
  registered: number
  expected_by_day: number | null
  unmet: number
  n_significant: number
  n_zips: number
  pace_ratio: number | null
  too_early: boolean
}

export interface Action {
  code: string
  label: string
  why: string
}

export interface PriorityItem {
  rank: number
  zip: string
  area: string
  lat: number
  lon: number
  expected_by_day: number
  observed: number
  gap_score: number
  unmet_estimate: number
  p_value: number
  significant: boolean
  svi: number
  priority: number
  actions: Action[]
}

export interface ZipDetail {
  zip: string
  area: string
  day: number
  lat: number
  lon: number
  housing_units: number
  svi: number
  hazard: {
    rain_total_in: number | null
    hwm_count: number | null
    hwm_max_ft: number | null
    damage_pts_per_1k_hu: number | null
    hazard_index: number | null
  }
  prediction: {
    expected_final: number
    lo80: number
    hi80: number
    model_version: string
    contributions: { feature: string; value: number }[]
  }
  gap: null | {
    expected_by_day: number
    observed: number
    gap_score: number
    unmet_estimate: number
    p_value: number
    significant: boolean
    priority: number
    rank: number
    status: 'flagged' | 'watch' | 'on_pace'
  }
  flag_history: { first_flagged_day: number | null; last_flagged_day: number | null; resolved: boolean }
  reasons: { text: string; label: DataLabel }[]
  actions: Action[]
  vulnerability: { key: string; label: string; value: number; median: number; p75: number; high: boolean }[]
  series: { day: number; observed: number; expected: number }[]
}

export interface PlanSite {
  site_id: string
  name: string
  kind: string
  lat: number
  lon: number
  source: string
  covered_zips: string[]
  covered_priority: number
  households_covered: number
  top_zips: { zip: string; area: string }[]
}

export interface Plan {
  plan_id: string
  day: number
  k: number
  radius_km: number
  sites: PlanSite[]
  coverage_pct: number
  households_covered: number
  sites_excluded_flooded: number
}

export interface Backtest {
  metrics: { day: number; method: string; k: number; precision: number; hits: number; n_true: number }[]
  definition: string
  labels: Record<string, boolean>
  top25_day5: string[]
}

export interface Forecast {
  day: number
  expected_final_total: number
  observed_to_date: number
  remaining_need: number
  visits_per_adjuster_per_day: number
  adjusters: number
  adjuster_days_needed: number
  days_to_clear: number
  curve: { day: number; observed: number; expected_final: number }[]
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

export const api = {
  events: () => get<EventInfo[]>('/events'),
  event: (id: string) => get<EventInfo>(`/events/${id}`),
  map: (id: string, day: number) => get<ZipFeatureCollection>(`/events/${id}/map?day=${day}`),
  kpis: (id: string, day: number) => get<Kpis>(`/events/${id}/kpis?day=${day}`),
  priorities: (id: string, day: number, sigOnly = false, limit = 20) =>
    get<{ items: PriorityItem[] }>(
      `/events/${id}/priorities?day=${day}&limit=${limit}&significant_only=${sigOnly}`,
    ),
  zip: (id: string, zip: string, day: number) => get<ZipDetail>(`/events/${id}/zips/${zip}?day=${day}`),
  backtest: (id: string) => get<Backtest>(`/events/${id}/backtest`),
  forecast: (id: string, day: number, visits: number, adjusters: number) =>
    get<Forecast>(`/events/${id}/forecast?day=${day}&visits_per_day=${visits}&adjusters=${adjusters}`),
  briefUrl: (id: string, day: number, visits: number, adjusters: number) =>
    `${BASE}/events/${id}/brief?day=${day}&visits_per_day=${visits}&adjusters=${adjusters}`,
  brief: async (id: string, day: number, visits: number, adjusters: number) => {
    const r = await fetch(api.briefUrl(id, day, visits, adjusters))
    if (!r.ok) throw new Error(await r.text())
    return r.text()
  },
  plan: async (id: string, body: { day: number; k: number; radius_km: number; exclude_flooded: boolean }) => {
    const r = await fetch(`${BASE}/events/${id}/plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok) throw new Error(await r.text())
    return r.json() as Promise<Plan>
  },
}
