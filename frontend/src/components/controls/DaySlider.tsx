import { useEffect, useRef, useState } from 'react'
import { dayDate } from '../../lib/format'

interface Props {
  day: number
  maxDay: number
  landfall: string
  onChange: (d: number) => void
  onPrefetch?: (d: number) => void
}

/** Day 0..max with a play button that advances one day per second. */
export function DaySlider({ day, maxDay, landfall, onChange, onPrefetch }: Props) {
  const [playing, setPlaying] = useState(false)
  const dayRef = useRef(day)
  dayRef.current = day

  useEffect(() => {
    if (!playing) return
    const t = setInterval(() => {
      const next = dayRef.current + 1
      if (next > maxDay) {
        setPlaying(false)
        return
      }
      onChange(next)
      onPrefetch?.(next + 1)
    }, 1000)
    return () => clearInterval(t)
  }, [playing, maxDay, onChange, onPrefetch])

  return (
    <div className="flex min-w-0 flex-1 items-center gap-3">
      <button
        onClick={() => {
          if (!playing && day >= maxDay) onChange(0)
          setPlaying((p) => !p)
        }}
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gap text-white hover:bg-red-500"
        aria-label={playing ? 'Pause' : 'Play'}
      >
        {playing ? (
          <svg width="12" height="12" viewBox="0 0 12 12"><rect x="2" y="1" width="3" height="10" fill="currentColor" /><rect x="7" y="1" width="3" height="10" fill="currentColor" /></svg>
        ) : (
          <svg width="12" height="12" viewBox="0 0 12 12"><path d="M3 1l8 5-8 5z" fill="currentColor" /></svg>
        )}
      </button>
      <div className="w-36 shrink-0 text-sm">
        <div className="num font-semibold">Day {day}</div>
        <div className="text-xs text-muted">{dayDate(landfall, day)}</div>
      </div>
      <input
        type="range"
        min={0}
        max={maxDay}
        value={day}
        onChange={(e) => onChange(Number(e.target.value))}
        onPointerMove={(e) => {
          const r = (e.target as HTMLInputElement).getBoundingClientRect()
          onPrefetch?.(Math.round(((e.clientX - r.left) / r.width) * maxDay))
        }}
        className="min-w-24 flex-1"
        aria-label="Day since landfall"
      />
    </div>
  )
}
