import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { Card, DataBadge } from '../components/ui'
import { useEventState } from '../hooks/useEventState'
import { fmtInt, fmtPred } from '../lib/format'

/** Very small Markdown renderer for the brief (headings, tables, lists, bold). */
function renderMd(md: string) {
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
  const inline = (s: string) => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/_(.+?)_/g, '<i>$1</i>')
  const lines = md.split('\n')
  const out: string[] = []
  let i = 0
  while (i < lines.length) {
    const l = lines[i]
    if (l.startsWith('|')) {
      const rows: string[] = []
      while (i < lines.length && lines[i].startsWith('|')) rows.push(lines[i++])
      const cells = (r: string) => r.split('|').slice(1, -1).map((c) => c.trim())
      out.push('<table class="w-full text-xs my-2"><thead><tr>' + cells(rows[0]).map((c) => `<th class="text-left border-b border-line py-1 pr-2">${inline(c)}</th>`).join('') + '</tr></thead><tbody>')
      for (const r of rows.slice(2)) out.push('<tr>' + cells(r).map((c) => `<td class="border-b border-line/50 py-1 pr-2 num">${inline(c)}</td>`).join('') + '</tr>')
      out.push('</tbody></table>')
      continue
    }
    if (l.startsWith('# ')) out.push(`<h1 class="text-xl font-bold mb-1">${inline(l.slice(2))}</h1>`)
    else if (l.startsWith('## ')) out.push(`<h2 class="text-base font-semibold mt-4 mb-1">${inline(l.slice(3))}</h2>`)
    else if (l.startsWith('> ')) out.push(`<div class="border-l-2 border-sim pl-2 text-sim text-xs my-1">${inline(l.slice(2))}</div>`)
    else if (/^\d+\. /.test(l)) out.push(`<div class="text-sm my-0.5">${inline(l)}</div>`)
    else if (l === '---') out.push('<hr class="border-line my-3"/>')
    else if (l.trim()) out.push(`<p class="text-sm">${inline(l)}</p>`)
    i++
  }
  return out.join('\n')
}

export default function BriefPage() {
  const { eventId, day } = useEventState()
  const [visits, setVisits] = useState(6)
  const [adjusters, setAdjusters] = useState(1000)
  const fc = useQuery({
    queryKey: ['forecast', eventId, day, visits, adjusters],
    queryFn: () => api.forecast(eventId, day, visits, adjusters),
    placeholderData: (p) => p,
  })
  const brief = useQuery({
    queryKey: ['brief', eventId, day, visits, adjusters],
    queryFn: () => api.brief(eventId, day, visits, adjusters),
    placeholderData: (p) => p,
  })
  const [copied, setCopied] = useState(false)

  return (
    <div className="flex h-full">
      <div className="flex w-[420px] shrink-0 flex-col gap-3 overflow-y-auto border-r border-line p-4">
        <h2 className="text-lg font-semibold">Claim-surge forecast · day {day}</h2>
        <Card className="space-y-2 p-3 text-sm">
          <label className="flex items-center justify-between gap-2">
            Visits per adjuster per day
            <input type="number" min={1} max={50} value={visits} onChange={(e) => setVisits(Math.max(1, +e.target.value))}
              className="num w-20 rounded border border-line bg-panel-2 px-2 py-0.5 text-right" />
          </label>
          <label className="flex items-center justify-between gap-2">
            Adjusters deployed
            <input type="number" min={1} value={adjusters} onChange={(e) => setAdjusters(Math.max(1, +e.target.value))}
              className="num w-20 rounded border border-line bg-panel-2 px-2 py-0.5 text-right" />
          </label>
        </Card>
        {fc.data && (
          <div className="grid grid-cols-2 gap-2">
            <Card className="p-2.5">
              <div className="flex justify-between text-[11px] text-muted">Remaining need <DataBadge label="predicted" /></div>
              <div className="num text-xl font-semibold">{fmtPred(fc.data.remaining_need)}</div>
            </Card>
            <Card className="p-2.5">
              <div className="text-[11px] text-muted">Days to clear</div>
              <div className="num text-xl font-semibold text-yellow-300">{fc.data.days_to_clear.toFixed(0)}</div>
              <div className="num text-[10px] text-muted">{fmtInt(fc.data.adjuster_days_needed)} adjuster-days</div>
            </Card>
          </div>
        )}
        <Card className="p-3">
          <div className="mb-1 text-xs text-muted">Registrations to date vs expected total</div>
          <div className="h-48">
            <ResponsiveContainer>
              <LineChart data={fc.data?.curve} margin={{ left: 0, right: 8 }}>
                <CartesianGrid stroke="#263140" strokeDasharray="3 3" />
                <XAxis dataKey="day" tick={{ fill: '#8b98a8', fontSize: 10 }} />
                <YAxis tick={{ fill: '#8b98a8', fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                <Tooltip contentStyle={{ background: '#121820', border: '1px solid #263140', fontSize: 12 }}
                  formatter={(v, n) => [fmtInt(Number(v)), n === 'observed' ? 'Observed (Real)' : 'Expected total (Predicted)']} labelFormatter={(l) => `Day ${l}`} />
                <Line dataKey="expected_final" stroke="#a78bfa" strokeDasharray="5 3" dot={false} />
                <Line dataKey="observed" stroke="#ef4444" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <div className="flex gap-2">
          <a href={api.briefUrl(eventId, day, visits, adjusters)}
            className="flex-1 rounded-md bg-gap py-2 text-center text-sm font-semibold text-white hover:bg-red-500">
            Download brief (.md)
          </a>
          <button
            onClick={async () => {
              const summary = brief.data?.split('## Summary')[1]?.split('##')[0]?.trim() ?? ''
              await navigator.clipboard.writeText(summary.replace(/\*\*/g, ''))
              setCopied(true)
              setTimeout(() => setCopied(false), 1500)
            }}
            className="rounded-md border border-line px-3 text-sm text-muted hover:text-text"
          >
            {copied ? 'Copied' : 'Copy summary'}
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-3xl rounded-lg border border-line bg-panel p-6">
          {brief.data ? <div dangerouslySetInnerHTML={{ __html: renderMd(brief.data) }} /> : <div className="text-muted">Building brief…</div>}
        </div>
      </div>
    </div>
  )
}
