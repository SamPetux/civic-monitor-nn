'use client'
import { useEffect, useState, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { api } from '@/lib/api'
import type { Topic, Burst } from '@/lib/types'
import Navbar from '@/components/Navbar'
import PeriodPicker from '@/components/PeriodPicker'
import { usePeriod } from '@/lib/usePeriod'
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'

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

const PALETTE = [
  '#6366f1','#f59e0b','#10b981','#ef4444','#3b82f6',
  '#8b5cf6','#ec4899','#14b8a6','#f97316','#84cc16',
]

function TopicsDonut({ topics }: { topics: Topic[] }) {
  if (!topics.length) return null
  const total = topics.reduce((s, t) => s + t.count, 0)
  const data = topics.map(t => ({
    name: t.label || `Тема ${t.topic_id}`,
    value: t.count,
    pct: ((t.count / total) * 100).toFixed(1),
  }))
  return (
    <div className="mt-4">
      <p className="text-xs text-gray-500 font-medium mb-2">Распределение сообщений по темам</p>
      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie data={data} cx="50%" cy="45%" innerRadius={60} outerRadius={95} paddingAngle={2} dataKey="value">
            {data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
          </Pie>
          <Tooltip
            formatter={(value: number, _: string, props: any) => [`${value} сообщ. (${props.payload.pct}%)`, props.payload.name]}
            contentStyle={{ fontSize: 11, borderRadius: 8, border: '1px solid #e5e7eb' }}
          />
          <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 10, lineHeight: '18px' }}
            formatter={(v: string) => v.length > 24 ? v.slice(0, 24) + '…' : v} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

function BurstsHeatmap({ bursts }: { bursts: Burst[] }) {
  if (!bursts.length) return null

  const topicsSet = Array.from(new Set(bursts.map(b => b.topic_label))).slice(0, 12)
  const datesSet = Array.from(new Set(bursts.map(b => b.date.slice(0, 10)))).sort()

  type CellData = { volume: number; intensity: string; z: number } | null
  const matrix: Record<string, Record<string, CellData>> = {}
  for (const t of topicsSet) {
    matrix[t] = {}
    for (const d of datesSet) matrix[t][d] = null
  }
  for (const b of bursts) {
    const t = b.topic_label
    const d = b.date.slice(0, 10)
    if (matrix[t] && d in matrix[t]) {
      matrix[t][d] = { volume: b.volume, intensity: b.intensity, z: b.z_score }
    }
  }

  // Показываем каждую N-ю дату в зависимости от количества
  const step = Math.max(1, Math.floor(datesSet.length / 12))
  const labelDates = new Set(datesSet.filter((_, i) => i % step === 0))

  const CELL_SIZE = 22 // px — размер ячейки

  return (
    <div className="mt-4 overflow-x-auto">
      <table style={{ borderSpacing: 3, borderCollapse: 'separate' }}>
        <thead>
          <tr>
            {/* Колонка с названиями тем */}
            <th style={{ minWidth: 160, paddingRight: 8 }} className="text-left text-xs text-gray-400 font-normal pb-1 align-bottom">
              Тема
            </th>
            {datesSet.map(d => (
              <th key={d} style={{ width: CELL_SIZE, minWidth: CELL_SIZE }} className="text-center pb-1 align-bottom">
                {labelDates.has(d) && (
                  <div style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', fontSize: 9, color: '#9ca3af', whiteSpace: 'nowrap', height: 44 }}>
                    {d.slice(5)}
                  </div>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {topicsSet.map(topic => (
            <tr key={topic}>
              <td style={{ paddingRight: 8, paddingTop: 2, paddingBottom: 2 }}
                className="text-xs text-gray-600 whitespace-nowrap max-w-[160px] truncate"
                title={topic}>
                {topic.length > 22 ? topic.slice(0, 22) + '…' : topic}
              </td>
              {datesSet.map(d => {
                const cell = matrix[topic][d]
                const bg = cell
                  ? cell.intensity === 'high' ? '#ef4444'
                  : cell.intensity === 'medium' ? '#fb923c'
                  : '#fde68a'
                  : '#f3f4f6'
                const opacity = cell ? Math.min(1, 0.5 + cell.z / 25) : 1
                return (
                  <td key={d} style={{ padding: 0 }}>
                    <div
                      title={cell ? `${topic}\n${d}\nz=${cell.z.toFixed(1)}, ${cell.volume} сообщ.` : undefined}
                      style={{
                        width: CELL_SIZE, height: CELL_SIZE,
                        backgroundColor: bg,
                        opacity,
                        borderRadius: 4,
                        cursor: cell ? 'default' : undefined,
                        transition: 'opacity 0.15s',
                      }}
                    />
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex gap-5 mt-3 text-xs text-gray-500">
        {[
          { color: '#ef4444', label: 'высокий' },
          { color: '#fb923c', label: 'средний' },
          { color: '#fde68a', label: 'низкий' },
          { color: '#f3f4f6', label: 'нет всплеска' },
        ].map(({ color, label }) => (
          <span key={label} className="flex items-center gap-1.5">
            <span style={{ width: 12, height: 12, borderRadius: 3, backgroundColor: color, display: 'inline-block', border: '1px solid #e5e7eb' }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}

function TopicsContent() {
  const { start, end, setPeriod } = usePeriod()
  const params = useSearchParams()
  const [districtId, setDistrictId] = useState(params.get('district') ?? '_city')
  const [topics, setTopics] = useState<Topic[]>([])
  const [bursts, setBursts] = useState<Burst[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api.topics(districtId, start, end, 10),
      api.bursts(districtId, start, end, 50),
    ]).then(([t, b]) => { setTopics(t); setBursts(b) })
      .finally(() => setLoading(false))
  }, [districtId, start, end])

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar active="topics" />
      <div className="flex-1 max-w-7xl mx-auto w-full px-4 py-6">
        {/* Фильтры */}
        <div className="flex flex-wrap gap-4 mb-6 items-end">
          <PeriodPicker start={start} end={end} onChange={setPeriod} />
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

        {/* Верхний ряд: топ тем + доnut | всплески список */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
            <h2 className="font-semibold text-gray-800 mb-4">Топ тем</h2>
            {loading ? <p className="text-gray-400 text-sm">Загрузка…</p>
              : topics.length === 0 ? <p className="text-gray-400 text-sm">Нет данных</p>
              : (
                <>
                  <div className="space-y-3">
                    {topics.map(t => (
                      <div key={t.topic_id} className="flex items-start gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-medium text-sm text-gray-800 truncate">
                              {t.label || `Тема ${t.topic_id}`}
                            </span>
                            <span className="text-xs text-gray-400">{t.count} сообщ.</span>
                          </div>
                          <p className="text-xs text-gray-400 truncate">{t.keywords}</p>
                        </div>
                        <div className="shrink-0 text-right">
                          <span className={`text-sm font-semibold ${t.neg_share > 0.3 ? 'text-red-500' : 'text-gray-500'}`}>
                            {(t.neg_share * 100).toFixed(0)}%
                          </span>
                          <div className="w-20 h-1.5 bg-gray-100 rounded-full mt-1 overflow-hidden">
                            <div className="h-full bg-red-400 rounded-full" style={{ width: `${t.neg_share * 100}%` }} />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                  <TopicsDonut topics={topics} />
                </>
              )}
          </div>

          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
            <h2 className="font-semibold text-gray-800 mb-4">Всплески активности</h2>
            {loading ? <p className="text-gray-400 text-sm">Загрузка…</p>
              : bursts.length === 0 ? <p className="text-gray-400 text-sm">Нет всплесков за период</p>
              : (
                <div className="space-y-2 max-h-[520px] overflow-y-auto pr-1">
                  {bursts.slice(0, 25).map((b, i) => (
                    <div key={i} className="flex items-center gap-3 py-2 border-b border-gray-50 last:border-0">
                      <span className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${INTENSITY_COLOR[b.intensity]}`}>
                        {b.intensity}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-800 truncate">{b.topic_label}</p>
                        <p className="text-xs text-gray-400">
                          {b.date.slice(0, 10)} · z={b.z_score.toFixed(1)} · {b.volume} сообщ.
                        </p>
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

        {/* Heatmap на всю ширину */}
        {!loading && bursts.length > 0 && (
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
            <h2 className="font-semibold text-gray-800 mb-1">Карта всплесков</h2>
            <p className="text-xs text-gray-400 mb-4">
              Каждая ячейка — всплеск по теме в конкретный день. Наведи для деталей.
            </p>
            <BurstsHeatmap bursts={bursts} />
          </div>
        )}
      </div>
    </div>
  )
}

export default function TopicsPage() {
  return <Suspense><TopicsContent /></Suspense>
}