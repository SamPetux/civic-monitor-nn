'use client'
import { useEffect, useState, useCallback } from 'react'
import dynamic from 'next/dynamic'
import { api } from '@/lib/api'
import type { DistrictMetrics } from '@/lib/types'
import type { FeatureCollection } from 'geojson'
import Navbar from './Navbar'
import PeriodPicker from './PeriodPicker'
import DistrictPanel from './DistrictPanel'
import { format, subDays } from 'date-fns'

// MapLibre нельзя на сервере — ssr: false
const DistrictMap = dynamic(() => import('./DistrictMap'), { ssr: false, loading: () => (
  <div className="w-full h-full flex items-center justify-center bg-gray-100 text-gray-400 text-sm">
    Загрузка карты…
  </div>
)})

export default function Dashboard() {
  const [start, setStart] = useState(() => {
    const end = new Date()
    const start = new Date(end.getTime() - 30 * 86400_000)
    return format(start, "yyyy-MM-dd'T'HH:mm:ss")
  })
  const [end, setEnd] = useState(() => format(new Date(), "yyyy-MM-dd'T'HH:mm:ss"))
  const [selectedId, setSelectedId] = useState<string | null>('avtozavodsky')
  const [metrics, setMetrics]     = useState<DistrictMetrics[]>([])
  const [geojson, setGeojson]     = useState<FeatureCollection | null>(null)
  const [refreshStatus, setRefreshStatus] = useState<{ is_running: boolean; last_result: string | null }>({ is_running: false, last_result: null })

  // Загрузка GeoJSON один раз
  useEffect(() => { api.geoJson().then(setGeojson) }, [])

  // Загрузка метрик при изменении периода
  useEffect(() => {
    api.metrics(start, end).then(setMetrics)
  }, [start, end])

  // Опрос статуса обновления
  useEffect(() => {
    const poll = () => api.refreshStatus().then(s => setRefreshStatus(s))
    poll()
    const id = setInterval(poll, 10_000)
    return () => clearInterval(id)
  }, [])

  const selectedMetrics = metrics.find(m => m.district_id === selectedId) ?? null

  const handleRefresh = useCallback(async () => {
    await api.refreshStart(24, undefined, 50)
    setRefreshStatus(s => ({ ...s, is_running: true }))
  }, [])

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <Navbar active="map" />

      {/* Панель фильтров */}
      <div className="bg-white border-b border-gray-100 px-4 py-2 flex items-center gap-4 flex-wrap">
        <PeriodPicker start={start} end={end} onChange={(s, e) => { setStart(s); setEnd(e) }} />

        <div className="ml-auto flex items-center gap-2">
          {refreshStatus.last_result === 'done' && (
            <span className="text-xs text-green-600 bg-green-50 px-2 py-1 rounded-lg">✓ Обновлено</span>
          )}
          {refreshStatus.last_result === 'failed' && (
            <span className="text-xs text-red-600 bg-red-50 px-2 py-1 rounded-lg">✗ Ошибка</span>
          )}
          <button
            onClick={refreshStatus.is_running ? undefined : handleRefresh}
            disabled={refreshStatus.is_running}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors
              ${refreshStatus.is_running
                ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                : 'bg-indigo-600 text-white hover:bg-indigo-700'}`}>
            {refreshStatus.is_running ? '⟳ Обновляется…' : '⟳ Обновить данные'}
          </button>
        </div>
      </div>

      {/* Основной контент: карта + панель */}
      <div className="flex-1 flex overflow-hidden">
        {/* Карта */}
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

          {/* Легенда */}
          <div className="absolute bottom-6 left-4 bg-white/90 backdrop-blur rounded-xl shadow-sm border border-gray-100 p-3">
            <p className="text-xs text-gray-500 mb-1.5 font-medium">Негативность</p>
            <div className="flex items-center gap-1.5">
              <div className="w-24 h-2.5 rounded-full" style={{
                background: 'linear-gradient(to right, #2ecc71, #a3d977, #f1c40f, #e67e22, #e74c3c)'
              }} />
            </div>
            <div className="flex justify-between text-xs text-gray-400 mt-1">
              <span>низкая</span><span>высокая</span>
            </div>
          </div>
        </div>

        {/* Панель района */}
        <div className="w-96 border-l border-gray-100 bg-white overflow-hidden flex flex-col">
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