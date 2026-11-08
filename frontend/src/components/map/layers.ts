import type { ExpressionSpecification } from 'maplibre-gl'

export type LayerKey = 'gap' | 'hazard' | 'vulnerability' | 'expected'

export interface LayerDef {
  key: LayerKey
  label: string
  color: ExpressionSpecification
  legend: { label: string; stops: string[]; ticks: string[] }
}

const NODATA = '#1c2430'

// Sequential ramps (light-to-saturated against a dark basemap).
const RED = ['#2a1416', '#5c1a1d', '#991b1b', '#dc2626', '#f87171']
const BLUE = ['#0f1d33', '#173a6b', '#1d5bb0', '#3b82f6', '#93c5fd']
const PURPLE = ['#1d1730', '#352560', '#5b3aa0', '#8b5cf6', '#c4b5fd']
const AMBER = ['#241a0c', '#4d3410', '#8a5a12', '#d97706', '#fcd34d']

function ramp(prop: ExpressionSpecification, domain: number[], colors: string[]): ExpressionSpecification {
  const stops: (number | string)[] = []
  domain.forEach((d, i) => stops.push(d, colors[i]))
  return [
    'case',
    ['==', prop, null],
    NODATA,
    ['interpolate', ['linear'], prop, ...stops],
  ] as unknown as ExpressionSpecification
}

export const LAYERS: Record<LayerKey, LayerDef> = {
  gap: {
    key: 'gap',
    label: 'Gap',
    // Only significant gaps reach full red; non-significant gaps stay muted.
    color: [
      'case',
      ['==', ['get', 'gap_score'], null],
      NODATA,
      ['!', ['get', 'significant']],
      ['interpolate', ['linear'], ['get', 'gap_score'], 0, '#161d26', 1, '#3a1d22'],
      ['interpolate', ['linear'], ['get', 'gap_score'], 0, RED[1], 0.3, RED[2], 0.55, RED[3], 0.8, RED[4]],
    ] as unknown as ExpressionSpecification,
    legend: { label: 'Share of expected requests missing', stops: RED.slice(1), ticks: ['0%', '30%', '55%', '80%+'] },
  },
  hazard: {
    key: 'hazard',
    label: 'Hazard',
    color: ramp(['get', 'rain_in'], [15, 25, 35, 45, 55], BLUE),
    legend: { label: 'Storm rainfall (inches)', stops: BLUE, ticks: ['15', '25', '35', '45', '55+'] },
  },
  vulnerability: {
    key: 'vulnerability',
    label: 'Vulnerability',
    color: ramp(['get', 'svi'], [0, 0.25, 0.5, 0.75, 1], PURPLE),
    legend: { label: 'Social Vulnerability Index (percentile)', stops: PURPLE, ticks: ['0', '25', '50', '75', '100'] },
  },
  expected: {
    key: 'expected',
    label: 'Expected need',
    color: ramp(
      ['/', ['coalesce', ['get', 'expected_final'], 0], ['max', ['get', 'housing_units'], 1]] as unknown as ExpressionSpecification,
      [0, 0.05, 0.12, 0.22, 0.35],
      AMBER,
    ),
    legend: { label: 'Expected households needing help, per home', stops: AMBER, ticks: ['0', '5%', '12%', '22%', '35%'] },
  },
}
