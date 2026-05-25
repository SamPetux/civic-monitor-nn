'use client'
import { useEffect, useState, useRef, useCallback, Suspense } from 'react'
import Navbar from '@/components/Navbar'
import { api } from '@/lib/api'
import type { SentimentBucket, Burst } from '@/lib/types'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis,
  Tooltip, ResponsiveContainer, CartesianGrid, Cell, ReferenceLine,
} from 'recharts'
import { format, subDays, addDays, parseISO, differenceInDays } from 'date-fns'

const DISTRICTS = [
  { id: 'avtozavodsky', name: 'Автозаводский' },
  { id: 'kanavinsky',   name: 'Канавинский' },
  { id: 'leninsky',     name: 'Ленинский' },
  { id: 'moskovsky',    name: 'Московский' },
  { id: 'nizhegorodsky',name: 'Нижегородский' },
  { id: 'priokskiy',    name: 'Приокский' },
  { id: 'sovetsky',     name: 'Советский' },
  { id: 'sormovsky',    name: 'Сормовский' },
]

const SPEED_OPTIONS = [
  { label: '0.5×', ms: 2000 },
  { label: '1×',   ms: 1000 },
  { label: '2×',   ms: 500 },
  { label: '5×',   ms: 200 },
]

const WINDOW_OPTIONS = [7, 14, 30]

// Суммируем тональности за окно
function sumBuckets(buckets: SentimentBucket[], from: Date, to: Date) {
  let neg = 0, neu = 0, pos = 0
  for (const b of buckets) {
    const d = parseISO(b.date.slice(0, 10))
    if (d >= from && d < to) {
      neg += b.negative; neu += b.neutral; pos += b.positive
    }
  }
  const total = neg + neu + pos
  return { neg, neu, pos, total, neg_share: total ? neg / total : 0 }
}

function AnalyticsContent() {
  const [dataStart, setDataStart] = useState<Date | null>(null)
  const [dataEnd,   setDataEnd]   = useState<Date | null>(null)

  // Загруженные ряды: districtId → массив бакетов
  const [series, setSeries]   = useState<Record<string, SentimentBucket[]>>({})
  const [bursts, setBursts]   = useState<Burst[]>([])
  const [loading, setLoading] = useState(true)

  // Состояние плеера
  const [windowDays, setWindowDays] = useState(14)
  const [cursorIdx, setCursorIdx]   = useState(0)   // индекс в массиве дней
  const [isPlaying, setIsPlaying]   = useState(false)
  const [speedIdx,  setSpeedIdx]    = useState(1)    // индекс в SPEED_OPTIONS
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Все дни между dataStart и dataEnd
  const allDays = useRef<Date[]>([])

  // --- Загрузка данных ---
  useEffect(() => {
    async function load() {
      setLoading(true)
      const period = await api.period()
      if (!period.start || !period.end) { setLoading(false); return }

      const s = parseISO(period.start)
      const e = parseISO(period.end)
      setDataStart(s); setDataEnd(e)

      const days: Date[] = []
      let d = s
      while (d <= e) { days.push(d); d = addDays(d, 1) }
      allDays.current = days
      setCursorIdx(days.length - 1)

      const fmt = (dt: Date) => format(dt, "yyyy-MM-dd'T'HH:mm:ss")

      // Параллельно грузим все районы + всплески
      const [burstsData, ...districtSeries] = await Promise.all([
        api.bursts('_city', fmt(s), fmt(e), 200),
        ...DISTRICTS.map(dist =>
          api.sentiment(dist.id, fmt(s), fmt(e), 'day')
        ),
      ])

      const seriesMap: Record<string, SentimentBucket[]> = {}
      DISTRICTS.forEach((dist, i) => { seriesMap[dist.id] = districtSeries[i] })
      setSeries(seriesMap)
      setBursts(burstsData as Burst[])
      setLoading(false)
    }
    load()
  }, [])

  // --- Производные данные для текущего курсора ---
  const cursorDate   = allDays.current[cursorIdx] ?? new Date()
  const windowStart  = subDays(cursorDate, windowDays)

  // City-wide timeseries для главного графика (данные от dataStart до cursorDate)
  const cityTimeline = (() => {
    if (!Object.keys(series).length) return []
    // Агрегируем по дням из всех районов
    const byDay: Record<string, { negative: number; neutral: number; positive: number }> = {}
    for (const buckets of Object.values(series)) {
      for (const b of buckets) {
        const key = b.date.slice(0, 10)
        if (!byDay[key]) byDay[key] = { negative: 0, neutral: 0, positive: 0 }
        byDay[key].negative += b.negative
        byDay[key].neutral  += b.neutral
        byDay[key].positive += b.positive
      }
    }
    return Object.entries(byDay)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, v]) => ({
        date: date.slice(5),  // MM-DD
        fullDate: date,
        ...v,
        total: v.negative + v.neutral + v.positive,
      }))
  })()

  // Районы отсортированные по негативу в окне
  const districtRanking = DISTRICTS.map(dist => {
    const { neg_share, total } = sumBuckets(series[dist.id] ?? [], windowStart, cursorDate)
    return { ...dist, neg_share, total }
  }).sort((a, b) => b.neg_share - a.neg_share)

  // Всплески в окне
  const windowBursts = bursts.filter(b => {
    const d = parseISO(b.date.slice(0, 10))
    return d >= windowStart && d <= cursorDate && b.intensity === 'high'
  }).slice(0, 6)

  // --- Плеер ---
  const stopPlay = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    intervalRef.current = null
    setIsPlaying(false)
  }, [])

  const startPlay = useCallback(() => {
    if (!allDays.current.length) return
    setIsPlaying(true)
    intervalRef.current = setInterval(() => {
      setCursorIdx(prev => {
        if (prev >= allDays.current.length - 1) {
          stopPlay()
          return prev
        }
        return prev + 1
      })
    }, SPEED_OPTIONS[speedIdx].ms)
  }, [speedIdx, stopPlay])

  const togglePlay = () => isPlaying ? stopPlay() : startPlay()

  useEffect(() => { return () => stopPlay() }, [stopPlay])

  // При смене скорости во время воспроизведения — перезапустить
  useEffect(() => {
    if (isPlaying) { stopPlay(); startPlay() }
  }, [speedIdx]) // eslint-disable-line

  const totalDays = allDays.current.length

  if (loading) return (
    <div className="min-h-screen flex flex-col">
      <Navbar active="analytics" />
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-gray-400 text-sm">Загружаем данные всех районов…</p>
        </div>
      </div>
    </div>
  )

  if (!dataStart || !dataEnd) return (
    <div className="min-h-screen flex flex-col">
      <Navbar active="analytics" />
      <div className="flex-1 flex items-center justify-center text-gray-400">Нет данных</div>
    </div>
  )

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <Navbar active="analytics" />

      {/* Инфо-бар */}
      <div className="bg-white border-b border-gray-100 px-6 py-2 flex items-center gap-6 text-xs text-gray-500">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span className="font-medium text-gray-700">Civic Monitor НН</span>
          <span>— Аналитический таймлайн</span>
        </div>
        <div className="ml-auto flex items-center gap-6">
          <span>Окно: <strong className="text-gray-700">{format(windowStart, 'dd.MM')} — {format(cursorDate, 'dd.MM.yyyy')}</strong></span>
          <span>Период данных: {format(dataStart, 'dd.MM')} — {format(dataEnd, 'dd.MM.yyyy')}</span>
        </div>
      </div>

      <div className="flex-1 flex flex-col px-6 py-4 gap-4 overflow-hidden">

        {/* Основная строка: график + правая панель */}
        <div className="flex gap-4 flex-1 min-h-0">

          {/* Главный график — тональность по городу */}
          <div className="flex-1 bg-white rounded-2xl border border-gray-100 shadow-sm p-5 flex flex-col">
            <div className="flex items-center justify-between mb-3">
              <div>
                <h2 className="font-semibold text-gray-800">Динамика тональности — весь город</h2>
                <p className="text-xs text-gray-400">Стек негатив / нейтрал / позитив по дням</p>
              </div>
              <div className="flex items-center gap-3 text-xs">
                <span className="flex items-center gap-1"><span className="w-3 h-2 rounded-sm bg-red-400 inline-block" /> негатив</span>
                <span className="flex items-center gap-1"><span className="w-3 h-2 rounded-sm bg-gray-300 inline-block" /> нейтрал</span>
                <span className="flex items-center gap-1"><span className="w-3 h-2 rounded-sm bg-emerald-400 inline-block" /> позитив</span>
              </div>
            </div>
            <div className="flex-1 min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={cityTimeline} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                  <XAxis dataKey="date" tick={{ fontSize: 9 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 9 }} tickLine={false} axisLine={false} />
                  <Tooltip
                    contentStyle={{ fontSize: 11, borderRadius: 8, border: '1px solid #e5e7eb' }}
                    labelStyle={{ fontWeight: 600 }}
                  />
                  <Area dataKey="negative" name="Негатив" stackId="1" stroke="#ef4444" fill="#ef4444" fillOpacity={0.75} />
                  <Area dataKey="neutral"  name="Нейтрал" stackId="1" stroke="#d1d5db" fill="#d1d5db" fillOpacity={0.6} />
                  <Area dataKey="positive" name="Позитив" stackId="1" stroke="#10b981" fill="#10b981" fillOpacity={0.75} />
                  {/* Линия текущего курсора */}
                  <ReferenceLine
                    x={format(cursorDate, 'MM-dd')}
                    stroke="#6366f1"
                    strokeWidth={2}
                    strokeDasharray="4 2"
                    label={{ value: '▼', position: 'top', fontSize: 10, fill: '#6366f1' }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Правая панель */}
          <div className="w-72 flex flex-col gap-4">

            {/* Районы по негативу */}
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4 flex-1">
              <h3 className="text-sm font-semibold text-gray-800 mb-3">
                Рейтинг районов по негативу
              </h3>
              <div className="space-y-2">
                {districtRanking.map((d, i) => (
                  <div key={d.id}>
                    <div className="flex items-center justify-between text-xs mb-0.5">
                      <span className="text-gray-600 truncate">{d.name}</span>
                      <span className={`font-semibold ${d.neg_share > 0.25 ? 'text-red-500' : d.neg_share > 0.15 ? 'text-orange-500' : 'text-gray-500'}`}>
                        {(d.neg_share * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${
                          d.neg_share > 0.25 ? 'bg-red-400' :
                          d.neg_share > 0.15 ? 'bg-orange-400' : 'bg-emerald-400'
                        }`}
                        style={{ width: `${Math.min(100, d.neg_share * 100 * 3)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Всплески в окне */}
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
              <h3 className="text-sm font-semibold text-gray-800 mb-2">
                Всплески в окне
                {windowBursts.length > 0 && (
                  <span className="ml-2 text-xs bg-red-100 text-red-600 px-1.5 py-0.5 rounded-full">
                    {windowBursts.length}
                  </span>
                )}
              </h3>
              {windowBursts.length === 0 ? (
                <p className="text-xs text-gray-400">Нет высоких всплесков</p>
              ) : (
                <div className="space-y-1.5">
                  {windowBursts.map((b, i) => (
                    <div key={i} className="text-xs border-l-2 border-red-400 pl-2">
                      <p className="text-gray-700 font-medium truncate">{b.topic_label}</p>
                      <p className="text-gray-400">{b.date.slice(0, 10)} · z={b.z_score.toFixed(1)}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Таймлайн + управление */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm px-6 py-4">
          {/* Управление плеером */}
          <div className="flex items-center gap-4 mb-3">
            {/* Play/Pause */}
            <button
              onClick={togglePlay}
              className={`w-9 h-9 rounded-full flex items-center justify-center transition-colors shadow-sm ${
                isPlaying ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-indigo-50 hover:text-indigo-600'
              }`}
            >
              {isPlaying ? (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                  <rect x="2" y="1" width="4" height="12" rx="1" />
                  <rect x="8" y="1" width="4" height="12" rx="1" />
                </svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                  <path d="M3 1.5l9 5.5-9 5.5V1.5z" />
                </svg>
              )}
            </button>

            {/* В начало */}
            <button
              onClick={() => { stopPlay(); setCursorIdx(windowDays) }}
              className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
              title="В начало"
            >⏮</button>

            {/* Скорость */}
            <div className="flex gap-1">
              {SPEED_OPTIONS.map((s, i) => (
                <button key={i} onClick={() => setSpeedIdx(i)}
                  className={`text-xs px-2 py-1 rounded-lg transition-colors ${
                    speedIdx === i ? 'bg-indigo-100 text-indigo-600 font-medium' : 'text-gray-400 hover:text-gray-600'
                  }`}>
                  {s.label}
                </button>
              ))}
            </div>

            {/* Размер окна */}
            <div className="flex gap-1 ml-2">
              {WINDOW_OPTIONS.map(w => (
                <button key={w} onClick={() => setWindowDays(w)}
                  className={`text-xs px-2 py-1 rounded-lg transition-colors ${
                    windowDays === w ? 'bg-gray-100 text-gray-700 font-medium' : 'text-gray-400 hover:text-gray-600'
                  }`}>
                  {w}д
                </button>
              ))}
            </div>

            <div className="ml-auto text-xs text-gray-500 font-mono">
              {format(cursorDate, 'dd.MM.yyyy')}
            </div>
          </div>

          {/* Скраббер */}
          <div className="relative">
            <input
              type="range"
              min={windowDays}
              max={Math.max(windowDays, totalDays - 1)}
              value={cursorIdx}
              onChange={e => { stopPlay(); setCursorIdx(Number(e.target.value)) }}
              className="w-full accent-indigo-600 cursor-pointer"
              style={{ height: 4 }}
            />
            {/* Метки начала и конца */}
            <div className="flex justify-between text-xs text-gray-400 mt-1">
              <span>{format(dataStart, 'dd.MM.yyyy')}</span>
              <span>{format(dataEnd, 'dd.MM.yyyy')}</span>
            </div>

            {/* Маркеры всплесков на таймлайне */}
            <div className="absolute top-0 left-0 right-0 pointer-events-none" style={{ height: 4 }}>
              {bursts.filter(b => b.intensity === 'high').map((b, i) => {
                const d = parseISO(b.date.slice(0, 10))
                const idx = differenceInDays(d, dataStart)
                const pct = totalDays > 1 ? (idx / (totalDays - 1)) * 100 : 0
                if (pct < 0 || pct > 100) return null
                return (
                  <div
                    key={i}
                    title={`${b.topic_label} (${b.date.slice(0, 10)})`}
                    className="absolute w-1 h-3 bg-red-400 opacity-60 rounded-full"
                    style={{ left: `${pct}%`, top: -4, transform: 'translateX(-50%)' }}
                  />
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function AnalyticsPage() {
  return <Suspense><AnalyticsContent /></Suspense>
}
