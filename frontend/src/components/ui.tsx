import type { ReactNode } from 'react'
import type { DataLabel } from '../api/client'

const BADGE: Record<DataLabel | 'mock', { text: string; cls: string }> = {
  real: { text: 'Real', cls: 'text-real border-real/40 bg-real/10' },
  predicted: { text: 'Predicted', cls: 'text-pred border-pred/40 bg-pred/10' },
  simulated: { text: 'Simulated', cls: 'text-sim border-sim/40 bg-sim/10' },
  mock: { text: 'Mock', cls: 'text-sim border-sim/40 bg-sim/10' },
}

/** Every number in the app carries one of these, so judges know what is real. */
export function DataBadge({ label, source }: { label: DataLabel | 'mock'; source?: string }) {
  const b = BADGE[label]
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-px text-[10px] font-medium uppercase tracking-wide ${b.cls}`}>
      {b.text}
      {source ? ` · ${source}` : ''}
    </span>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-lg border border-line bg-panel ${className}`}>{children}</div>
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton ${className}`} />
}

export function MockBanner({ mode }: { mode?: string }) {
  if (mode !== 'mock') return null
  return (
    <div className="border-b border-sim/40 bg-sim/10 px-4 py-1 text-center text-xs text-sim">
      MOCK DATA: synthetic numbers on fake zones, for building the interface. Run the real pipeline to replace it.
    </div>
  )
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      onClick={() => onChange(!on)}
      className={`rounded-full border px-3 py-1 text-xs transition ${
        on ? 'border-gap bg-gap/15 text-red-200' : 'border-line text-muted hover:text-text'
      }`}
    >
      {label}
    </button>
  )
}
