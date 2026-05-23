'use client'
import { useEffect, useState, Suspense } from 'react'
import { api } from '@/lib/api'
import type { TopUser } from '@/lib/types'
import Navbar from '@/components/Navbar'
import PeriodPicker from '@/components/PeriodPicker'
import { usePeriod } from '@/lib/usePeriod'

function UsersContent() {
  const { start, end, setPeriod } = usePeriod()
  const [users, setUsers] = useState<TopUser[]>([])
  const [loading, setLoading] = useState(true)
  const [excluded, setExcluded] = useState<Set<number>>(new Set())

  useEffect(() => {
    setLoading(true)
    api.topUsers(start, end, 50)
      .then(setUsers)
      .finally(() => setLoading(false))
  }, [start, end])

  const toggle = (id: number) =>
    setExcluded(prev => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })

  const visible = users.filter(u => !excluded.has(u.user_id))
  const botCount = users.filter(u => u.suspected_bot).length

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar active="users" />
      <div className="flex-1 max-w-5xl mx-auto w-full px-4 py-6">
        <div className="flex flex-wrap gap-4 mb-6 items-end justify-between">
          <PeriodPicker start={start} end={end} onChange={setPeriod} />
          <div className="flex gap-3 text-sm text-gray-500">
            {excluded.size > 0 && (
              <button onClick={() => setExcluded(new Set())} className="text-indigo-500 hover:underline">
                Сбросить исключения ({excluded.size})
              </button>
            )}
            {botCount > 0 && (
              <span className="text-orange-500">⚠ {botCount} подозрительных аккаунтов</span>
            )}
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Автор</th>
                <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 uppercase">Комм.</th>
                <th className="text-center px-4 py-3 text-xs font-medium text-gray-500 uppercase">Тональность</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Районы</th>
                <th className="text-center px-4 py-3 text-xs font-medium text-gray-500 uppercase">Исключить</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} className="text-center py-8 text-gray-400">Загрузка…</td>
                </tr>
              ) : visible.map(u => (
                <tr
                  key={u.user_id}
                  className={`border-b border-gray-50 hover:bg-gray-50 transition-colors ${
                    excluded.has(u.user_id) ? 'opacity-40' : ''
                  }`}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <a
                        href={u.user_url}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-indigo-600 hover:underline"
                      >
                        {u.name}
                      </a>
                      {u.suspected_bot && (
                        <span className="text-xs bg-orange-100 text-orange-600 px-1.5 py-0.5 rounded-full">
                          бот?
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right font-medium">{u.comments_in_period}</td>
                  {/* C: тональность с числом */}
                  <td className="px-4 py-3 text-center">
                    <SentimentBadge value={u.avg_sentiment} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {u.districts.slice(0, 3).map(d => (
                        <span key={d} className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
                          {d}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <button
                      onClick={() => toggle(u.user_id)}
                      className={`w-6 h-6 rounded border-2 transition-colors ${
                        excluded.has(u.user_id)
                          ? 'bg-red-500 border-red-500 text-white'
                          : 'border-gray-300 hover:border-red-400'
                      }`}
                    >
                      {excluded.has(u.user_id) && '✕'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default function UsersPage() {
  return (
    <Suspense>
      <UsersContent />
    </Suspense>
  )
}

// C: цветной бейдж + числовое значение тональности
function SentimentBadge({ value }: { value: number }) {
  const isNeg = value < -0.1
  const isPos = value > 0.1
  const color = isNeg ? 'bg-red-100 text-red-600' : isPos ? 'bg-green-100 text-green-600' : 'bg-gray-100 text-gray-500'
  const arrow = isNeg ? '↓' : isPos ? '↑' : '–'
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${color}`}>
      {arrow} {value.toFixed(2)}
    </span>
  )
}
