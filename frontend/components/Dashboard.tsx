'use client'
import { useEffect, useState, useCallback } from 'react'
import dynamic from 'next/dynamic'
import { api } from '@/lib/api'
import type { DistrictMetrics } from '@/lib/types'
import type { FeatureCollection } from 'geojson'
import Navbar from './Navbar'
import PeriodPicker from './PeriodPicker'
import DistrictPanel from './DistrictPanel'
import { format } from 'date-fns'

const DistrictMap = dynamic(() => import('./DistrictMap'), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full flex items-center justify-center bg-gray-100 text-gray-400 text-sm">
      Загрузка карты…
    </div>
  ),
})

export default function Dashboard() {
  const [start, setStart] = useState(() => {
    const now = new Date()
    const s = new Date(now.getTime() - 30 * 86400_000)
    return format(s, "yyyy-MM-dd'T'HH:mm:ss")
  })
  const [end, setEnd] = useState(() => format(new Date(), "yyyy-MM-dd'T'HH:mm:ss"))
  const [selectedId, setSelectedId] = useState<string | null>('avtozavodsky')
  const [metrics, setMetrics] = useState<DistrictMetrics[]>([])
  const [geojson, setGeojson] = useState<FeatureCollection | null>(null)
  const [refreshStatus, setRefreshStatus] = useState<{
    is_running: boolean
    last_result: string | null
    log_tail?: string | null
  }>({ is_running: false, last_result: null })

  const [refreshOpen, setRefreshOpen] = useState(false)
  const [refreshHours, setRefreshHours] = useState(24)
  const [refreshUnit, setRefreshUnit] = useState<'hours' | 'days'>('hours')
  const [refreshMax, setRefreshMax] = useState(50)
  const [skipBursts, setSkipBursts] = useState(false)

  useEffect(() => { api.geoJson().then(setGeojson) }, [])
  useEffect(() => { api.metrics(start, end).then(setMetrics) }, [start, end])
  useEffect(() => {
    const poll = () => api.refreshStatus().then(s => setRefreshStatus(s))
    poll()
    const id = setInterval(poll, 10_000)
    return () => clearInterval(id)
  }, [])

  const selectedMetrics = metrics.find(m => m.district_id === selectedId) ?? null

  const handleRefresh = useCallback(async () => {
    const hours = refreshUnit === 'hours' ? refreshHours : undefined
    const days = refreshUnit === 'days' ? refreshHours : undefined
    await api.refreshStart(hours, days, refreshMax, skipBursts)
    setRefreshStatus(s => ({ ...s, is_running: true, last_result: null }))
    setRefreshOpen(false)
  }, [refreshHours, refreshUnit, refreshMax, skipBursts])

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <Navbar active="map" />

      <div className="bg-white border-b border-gray-100 px-4 py-2 flex items-center gap-4 flex-wrap">
        <PeriodPicker start={start} end={end} onChange={(s, e) => { setStart(s); setEnd(e) }} />

        <div className="ml-auto flex items-center gap-2 relative">
          {refreshStatus.last_result === 'done' && (
            <span className="text-xs text-green-600 bg-green-50 px-2 py-1 rounded-lg">✓ Обновлено</span>
          )}
          {refreshStatus.last_result === 'failed' && (
            <span className="text-xs text-red-600 bg-red-50 px-2 py-1 rounded-lg">✗ Ошибка обновления</span>
          )}

          {refreshStatus.is_running ? (
            <button disabled className="px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-100 text-gray-400 cursor-not-allowed">
              ⟳ Обновляется…
            </button>
          ) : (
            <div className="relative">
              <button
                onClick={() => setRefreshOpen(o => !o)}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors flex items-center gap-1"
              >
                ⟳ Обновить данные
                <span className="text-indigo-300">{refreshOpen ? '▲' : '▼'}</span>
              </button>

              {refreshOpen && (
                <div className="absolute right-0 top-full mt-1 w-72 bg-white border border-gray-200 rounded-xl shadow-lg p-4 z-50">
                  <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-3">
                    Параметры обновления
                  </p>

                  <div className="flex gap-1 mb-3">
                    {(['hours', 'days'] as const).map(u => (
                      <button
                        key={u}
                        onClick={() => setRefreshUnit(u)}
                        className={`flex-1 text-xs py-1.5 rounded-lg border transition-colors ${
                          refreshUnit === u
                            ? 'bg-indigo-50 border-indigo-300 text-indigo-600 font-medium'
                            : 'border-gray-200 text-gray-500 hover:bg-gray-50'
                        }`}
                      >
                        {u === 'hours' ? 'Часы' : 'Дни'}
                      </button>
                    ))}
                  </div>

                  <div className="mb-3">
                    <label className="text-xs text-gray-500 flex justify-between mb-1">
                      <span>Парсить за последние</span>
                      <span className="font-medium text-gray-700">
                        {refreshHours} {refreshUnit === 'hours' ? 'ч' : 'дн'}
                      </span>
                    </label>
                    <input
                      type="range" min={1}
                      max={refreshUnit === 'hours' ? 72 : 14}
                      value={refreshHours}
                      onChange={e => setRefreshHours(Number(e.target.value))}
                      className="w-full accent-indigo-600"
                    />
                    <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                      <span>{refreshUnit === 'hours' ? '1ч' : '1д'}</span>
                      <span>{refreshUnit === 'hours' ? '72ч' : '14д'}</span>
                    </div>
                  </div>

                  <div className="mb-3">
                    <label className="text-xs text-gray-500 flex justify-between mb-1">
                      <span>Постов на группу (макс)</span>
                      <span className="font-medium text-gray-700">{refreshMax}</span>
                    </label>
                    <input
                      type="range" min={10} max={200} step={10}
                      value={refreshMax}
                      onChange={e => setRefreshMax(Number(e.target.value))}
                      className="w-full accent-indigo-600"
                    />
                    <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                      <span>10</span><span>200</span>
                    </div>
                  </div>

                  <div className="mb-4">
                    <p className="text-xs text-gray-500 mb-2">Пересчитать после парсинга:</p>
                    <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer select-none">
                      <input
                        type="checkbox" checked={!skipBursts}
                        onChange={e => setSkipBursts(!e.target.checked)}
                        className="accent-indigo-600"
                      />
                      Всплески активности
                    </label>
                  </div>

                  <button
                    onClick={handleRefresh}
                    className="w-full py-2 bg-indigo-600 text-white text-xs font-medium rounded-lg hover:bg-indigo-700 transition-colors"
                  >
                    ▶ Запустить обновление
                  </button>

                  {refreshStatus.log_tail && (
                    <details className="mt-3">
                      <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600">
                        Лог последнего запуска
                      </summary>
                      <pre className="mt-1 text-xs bg-gray-50 rounded p-2 max-h-32 overflow-auto text-gray-600 whitespace-pre-wrap">
                        {refreshStatus.log_tail.slice(-1000)}
                      </pre>
                    </details>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 relative">
          {geojson ? (
            <DistrictMap
              geojson={geojson}
              metrics={metrics}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-gray-100 text-gray-400 text-sm">
              Загрузка…
            </div>
          )}

          <div className="absolute bottom-6 left-4 bg-white/90 backdrop-blur rounded-xl shadow-sm border border-gray-100 p-3">
            <p className="text-xs text-gray-500 mb-1.5 font-medium">Негативность</p>
            <div className="flex items-center gap-1.5">
              <div
                className="w-24 h-2.5 rounded-full"
                style={{ background: 'linear-gradient(to right, #2ecc71, #a3d977, #f1c40f, #e67e22, #e74c3c)' }}
              />
            </div>
            <div className="flex justify-between text-xs text-gray-400 mt-1">
              <span>низкая</span><span>высокая</span>
            </div>
          </div>
        </div>

        {/* A4: правая панель шире — 520px */}
        <div className="w-[520px] border-l border-gray-100 bg-white overflow-hidden flex flex-col">
          <DistrictPanel
            districtId={selectedId ?? 'avtozavodsky'}
            metrics={selectedMetrics}
            start={start}
            end={end}
          />
        </div>
      </div>
    </div>
  )
}
