'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { Topic, Burst } from '@/lib/types'
import Navbar from '@/components/Navbar'
import PeriodPicker from '@/components/PeriodPicker'
import { format, subDays } from 'date-fns'

const DISTRICTS = [
  { id: '_city', name: 'Весь город' },
  { id: 'avtozavodsky', name: 'Автозаводский' },
  { id: 'kanavinsky', name: 'Канавинский' },
  { id: 'leninsky', name: 'Ленинский' },
  { id: 'moskovsky', name: 'Московский' },
  { id: 'nizhegorodsky', name: 'Нижегородский' },
  { id: 'priokskiy', name: 'Приокский' },
  { id: 'sovetsky', name: 'Советский' },
  { id: 'sormovsky', name: 'Сормовский' },
]

const INTENSITY_COLOR: Record<string, string> = {
  high: 'bg-red-100 text-red-700',
  medium: 'bg-orange-100 text-orange-700',
  low: 'bg-gray-100 text-gray-600',
}

export default function TopicsPage() {
  const [start, setStart] = useState(() => format(subDays(new Date(), 30), "yyyy-MM-dd'T'HH:mm:ss"))
  const [end, setEnd]     = useState(() => format(new Date(), "yyyy-MM-dd'T'HH:mm:ss"))
  const [districtId, setDistrictId] = useState('_city')
  const [topics, setTopics] = useState<Topic[]>([])
  const [bursts, setBursts] = useState<Burst[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api.topics(districtId, start, end, 10),
      api.bursts(districtId, start, end, 20),
    ]).then(([t, b]) => { setTopics(t); setBursts(b) })
      .finally(() => setLoading(false))
  }, [districtId, start, end])

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar active="topics" />
      <div className="flex-1 max-w-7xl mx-auto w-full px-4 py-6">
        {/* Фильтры */}
        <div className="flex flex-wrap gap-4 mb-6 items-end">
          <PeriodPicker start={start} end={end} onChange={(s, e) => { setStart(s); setEnd(e) }} />
          <div>
            <label className="block text-xs text-gray-500 mb-1">Район</label>
            <select
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
              value={districtId}
              onChange={e => setDistrictId(e.target.value)}
            >
              {DISTRICTS.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Топ тем */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
            <h2 className="font-semibold text-gray-800 mb-4">Топ тем</h2>
            {loading ? <p className="text-gray-400 text-sm">Загрузка…</p> : topics.length === 0 ? (
              <p className="text-gray-400 text-sm">Нет данных</p>
            ) : (
              <div className="space-y-3">
                {topics.map(t => (
                  <div key={t.topic_id} className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium text-sm text-gray-800 truncate">{t.label || `Тема ${t.topic_id}`}</span>
                        <span className="text-xs text-gray-400">{t.count} сообщ.</span>
                      </div>
                      <p className="text-xs text-gray-400 truncate">{t.keywords}</p>
                    </div>
                    <div className="shrink-0 text-right">
                      <span className={`text-sm font-semibold ${t.neg_share > 0.3 ? 'text-red-500' : 'text-gray-500'}`}>
                        {(t.neg_share * 100).toFixed(0)}% neg
                      </span>
                      {/* bar */}
                      <div className="w-24 h-1.5 bg-gray-100 rounded-full mt-1 overflow-hidden">
                        <div className="h-full bg-red-400 rounded-full" style={{ width: `${t.neg_share * 100}%` }} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Всплески */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
            <h2 className="font-semibold text-gray-800 mb-4">Всплески активности</h2>
            {loading ? <p className="text-gray-400 text-sm">Загрузка…</p> : bursts.length === 0 ? (
              <p className="text-gray-400 text-sm">Нет всплесков за период</p>
            ) : (
              <div className="space-y-2">
                {bursts.map((b, i) => (
                  <div key={i} className="flex items-center gap-3 py-2 border-b border-gray-50 last:border-0">
                    <span className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${INTENSITY_COLOR[b.intensity]}`}>
                      {b.intensity}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">{b.topic_label}</p>
                      <p className="text-xs text-gray-400">{b.date.slice(0, 10)} · z={b.z_score.toFixed(1)} · {b.volume} сообщ.</p>
                    </div>
                    {b.neg_share != null && (
                      <span className="text-xs text-red-400 shrink-0">{(b.neg_share * 100).toFixed(0)}%↑</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}