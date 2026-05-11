'use client'
import { format, subDays, subMonths } from 'date-fns'

interface Props {
  start: string
  end: string
  onChange: (start: string, end: string) => void
}

const fmt = (d: Date) => format(d, "yyyy-MM-dd'T'HH:mm:ss")

const PRESETS = [
  { label: '24ч',    fn: () => [fmt(subDays(new Date(), 1)),   fmt(new Date())] },
  { label: '7д',     fn: () => [fmt(subDays(new Date(), 7)),   fmt(new Date())] },
  { label: '30д',    fn: () => [fmt(subDays(new Date(), 30)),  fmt(new Date())] },
  { label: '3мес',   fn: () => [fmt(subMonths(new Date(), 3)), fmt(new Date())] },
]

export default function PeriodPicker({ start, end, onChange }: Props) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <div>
        <label className="block text-xs text-gray-500 mb-1">С</label>
        <input type="datetime-local" value={start.slice(0, 16)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
          onChange={e => onChange(e.target.value + ':00', end)} />
      </div>
      <div>
        <label className="block text-xs text-gray-500 mb-1">По</label>
        <input type="datetime-local" value={end.slice(0, 16)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
          onChange={e => onChange(start, e.target.value + ':00')} />
      </div>
      <div className="flex gap-1">
        {PRESETS.map(p => (
          <button key={p.label}
            onClick={() => { const [s, e] = p.fn(); onChange(s, e) }}
            className="px-3 py-2 text-xs font-medium border border-gray-200 rounded-lg bg-white hover:bg-indigo-50 hover:border-indigo-300 hover:text-indigo-600 transition-colors">
            {p.label}
          </button>
        ))}
      </div>
    </div>
  )
}