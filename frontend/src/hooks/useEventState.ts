import { useQuery } from '@tanstack/react-query'
import { useCallback } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'

/** Event and day live in the URL so any view can be bookmarked and Back works. */
export function useEventState() {
  const { eventId = 'harvey-2017' } = useParams()
  const [params, setParams] = useSearchParams()
  const day = Number(params.get('day') ?? 5)
  const zip = params.get('zip')

  const event = useQuery({ queryKey: ['event', eventId], queryFn: () => api.event(eventId) })

  const set = useCallback(
    (patch: Record<string, string | number | null>) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          for (const [k, v] of Object.entries(patch)) {
            if (v == null) next.delete(k)
            else next.set(k, String(v))
          }
          return next
        },
        { replace: true },
      ),
    [setParams],
  )

  return {
    eventId,
    day,
    zip,
    event: event.data,
    setDay: (d: number) => set({ day: d }),
    setZip: (z: string | null) => set({ zip: z }),
  }
}

export function useMapDay(eventId: string, day: number) {
  return useQuery({
    queryKey: ['map', eventId, day],
    queryFn: () => api.map(eventId, day),
    staleTime: Infinity,
    placeholderData: (prev) => prev, // keep the old map while the next day loads
  })
}

export function useKpis(eventId: string, day: number) {
  return useQuery({
    queryKey: ['kpis', eventId, day],
    queryFn: () => api.kpis(eventId, day),
    staleTime: Infinity,
    placeholderData: (prev) => prev,
  })
}

export function usePriorities(eventId: string, day: number, sigOnly: boolean) {
  return useQuery({
    queryKey: ['priorities', eventId, day, sigOnly],
    queryFn: () => api.priorities(eventId, day, sigOnly),
    staleTime: Infinity,
    placeholderData: (prev) => prev,
  })
}
