import {
  Map as MLMap,
  Marker,
  NavigationControl,
  Popup,
  setWorkerUrl,
  type ExpressionSpecification,
  type GeoJSONSource,
  type StyleSpecification,
} from 'maplibre-gl'
// maplibre v6 loads its worker from a sibling file; Vite's dep pre-bundling breaks that
// relative path, so hand it the real file URL explicitly (works in dev and build).
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { useEffect, useRef, useState } from 'react'
import type { ZipFeatureCollection, ZipProps } from '../../api/client'

setWorkerUrl(workerUrl)

const BASEMAP = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
// Used when the basemap can't load (offline demo): plain background, ZIPs still render.
const BLANK: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#0b0f14' } }],
}

export interface MapSite {
  id: string
  name: string
  lat: number
  lon: number
  radius_km: number
}

interface Props {
  data?: ZipFeatureCollection
  fillColor: ExpressionSpecification
  bbox?: [number, number, number, number]
  selectedZip?: string | null
  flyTo?: { lon: number; lat: number; key: number } | null
  sites?: MapSite[]
  outlineSignificant?: boolean
  tooltip?: (p: ZipProps) => string
  onSelect?: (zip: string | null) => void
}

function circle(lon: number, lat: number, km: number, n = 64): [number, number][] {
  const pts: [number, number][] = []
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * 2 * Math.PI
    const dLat = (km / 111.32) * Math.sin(a)
    const dLon = (km / (111.32 * Math.cos((lat * Math.PI) / 180))) * Math.cos(a)
    pts.push([lon + dLon, lat + dLat])
  }
  return pts
}

export function ZipMap({
  data,
  fillColor,
  bbox,
  selectedZip,
  flyTo,
  sites,
  outlineSignificant = true,
  tooltip,
  onSelect,
}: Props) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<MLMap | null>(null)
  const [ready, setReady] = useState(false)
  const cb = useRef({ tooltip, onSelect })
  cb.current = { tooltip, onSelect }

  // create once
  useEffect(() => {
    if (!el.current) return
    let fellBack = false
    const m = new MLMap({
      container: el.current,
      style: BASEMAP,
      bounds: bbox,
      fitBoundsOptions: { padding: 20 },
      attributionControl: { compact: true },
    })
    map.current = m
    m.addControl(new NavigationControl({ showCompass: false }), 'top-left')
    m.on('error', (e) => {
      // basemap unreachable -> switch to a blank style once
      if (!fellBack && !m.isStyleLoaded() && String(e.error?.message ?? '').match(/fetch|network|style/i)) {
        fellBack = true
        m.setStyle(BLANK)
      }
    })
    const popup = new Popup({ closeButton: false, closeOnClick: false, offset: 8 })

    m.on('style.load', () => {
      const firstLabel = m.getStyle().layers?.find((l) => l.type === 'symbol')?.id
      m.addSource('zips', { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, promoteId: 'zip' })
      m.addLayer(
        { id: 'zip-fill', type: 'fill', source: 'zips', paint: { 'fill-color': '#1c2430', 'fill-opacity': 0.82 } },
        firstLabel,
      )
      m.addLayer(
        { id: 'zip-line', type: 'line', source: 'zips', paint: { 'line-color': '#0b0f14', 'line-width': 0.4 } },
        firstLabel,
      )
      m.addLayer({
        id: 'zip-sig',
        type: 'line',
        source: 'zips',
        filter: ['==', ['get', 'significant'], true],
        paint: { 'line-color': '#fecaca', 'line-width': 1.6, 'line-opacity': 0.9 },
      })
      m.addLayer({
        id: 'zip-hover',
        type: 'line',
        source: 'zips',
        paint: {
          'line-color': '#ffffff',
          'line-width': ['case', ['boolean', ['feature-state', 'hover'], false], 2, 0],
        },
      })
      m.addLayer({
        id: 'zip-selected',
        type: 'line',
        source: 'zips',
        filter: ['==', ['get', 'zip'], ''],
        paint: { 'line-color': '#facc15', 'line-width': 3 },
      })
      m.addSource('rings', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      m.addLayer({ id: 'ring-fill', type: 'fill', source: 'rings', paint: { 'fill-color': '#facc15', 'fill-opacity': 0.06 } })
      m.addLayer({
        id: 'ring-line',
        type: 'line',
        source: 'rings',
        paint: { 'line-color': '#facc15', 'line-width': 1.5, 'line-dasharray': [2, 2] },
      })
      setReady(true)
    })

    let hoverId: string | number | undefined
    m.on('mousemove', 'zip-fill', (e) => {
      const f = e.features?.[0]
      if (!f) return
      m.getCanvas().style.cursor = 'pointer'
      if (hoverId !== undefined) m.setFeatureState({ source: 'zips', id: hoverId }, { hover: false })
      hoverId = f.id
      if (hoverId !== undefined) m.setFeatureState({ source: 'zips', id: hoverId }, { hover: true })
      const html = cb.current.tooltip?.(f.properties as ZipProps)
      if (html) popup.setLngLat(e.lngLat).setHTML(html).addTo(m)
    })
    m.on('mouseleave', 'zip-fill', () => {
      m.getCanvas().style.cursor = ''
      if (hoverId !== undefined) m.setFeatureState({ source: 'zips', id: hoverId }, { hover: false })
      hoverId = undefined
      popup.remove()
    })
    m.on('click', 'zip-fill', (e) => {
      const z = e.features?.[0]?.properties?.zip as string | undefined
      cb.current.onSelect?.(z ?? null)
    })

    return () => {
      popup.remove()
      m.remove()
      map.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // the event (and its bbox) usually arrives after the map is created
  const bboxKey = bbox?.join(',')
  useEffect(() => {
    if (!ready || !bbox) return
    map.current!.fitBounds(bbox, { padding: 20, duration: 0 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, bboxKey])

  useEffect(() => {
    if (!ready || !data) return
    ;(map.current!.getSource('zips') as GeoJSONSource).setData(data as unknown as GeoJSON.FeatureCollection)
  }, [ready, data])

  useEffect(() => {
    if (!ready) return
    map.current!.setPaintProperty('zip-fill', 'fill-color', fillColor)
  }, [ready, fillColor])

  useEffect(() => {
    if (!ready) return
    map.current!.setLayoutProperty('zip-sig', 'visibility', outlineSignificant ? 'visible' : 'none')
  }, [ready, outlineSignificant])

  useEffect(() => {
    if (!ready) return
    map.current!.setFilter('zip-selected', ['==', ['get', 'zip'], selectedZip ?? ''])
  }, [ready, selectedZip])

  useEffect(() => {
    if (!ready || !flyTo) return
    map.current!.flyTo({ center: [flyTo.lon, flyTo.lat], zoom: Math.max(map.current!.getZoom(), 10.5), speed: 1.6 })
  }, [ready, flyTo])

  const markers = useRef<Marker[]>([])
  useEffect(() => {
    if (!ready) return
    const s = sites ?? []
    markers.current.forEach((mk) => mk.remove())
    markers.current = s.map((x, i) => {
      const pin = document.createElement('div')
      pin.className =
        'flex h-6 w-6 items-center justify-center rounded-full border-2 border-ink bg-yellow-400 text-[11px] font-bold text-ink shadow-lg'
      pin.textContent = String(i + 1)
      pin.title = x.name
      return new Marker({ element: pin }).setLngLat([x.lon, x.lat]).addTo(map.current!)
    })
    ;(map.current!.getSource('rings') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: s.map((x) => ({
        type: 'Feature',
        properties: {},
        geometry: { type: 'Polygon', coordinates: [circle(x.lon, x.lat, x.radius_km)] },
      })),
    })
  }, [ready, sites])

  return <div ref={el} className="h-full w-full" />
}
