'use client'
import { useEffect, useState, useCallback } from 'react'
import { api } from '@/lib/api'
import type { DistrictMetrics, Comment, SentimentBucket, Topic } from '@/lib/types'
import SentimentChart from './SentimentChart'
import CommentList from './CommentList'

interface Props {
  districtId: string
  metrics: DistrictMetrics | null
  start: string
  end: string
}

const SENT_FILTERS = [
  { value: '', label: 'Все' },
  { value: 'negative', label: '🔴 Негатив' },
  { value: 'neutral',  label: '⚪ Нейтрал' },
  { value: 'positive', label: '🟢 Позитив' },
]

export default function DistrictPanel({ districtId, metrics, start, end }: Props) {
  const [timeseries, setTimeseries] = useState<SentimentBucket[]>([])
  const [comments, setComments]     = useState<Comment[]>([])
  const [topics, setTopics]         = useState<Topic[]>([])
  const [bucket, setBucket]         = useState<'day' | 'hour'>('day')
  const [sentiment, setSentiment]   = useState('')
  const [loadingC, setLoadingC]     = useState(false)
  const [pdfLoading, setPdfLoading] = useState(false)

  useEffect(() => {
    api.sentiment(districtId, start, end, bucket).then(setTimeseries)
    api.topics(districtId, start, end, 5).then(setTopics)
  }, [districtId, start, end, bucket])

  useEffect(() => {
    setLoadingC(true)
    api.comments(districtId, start, end, sentiment || null, 30)
      .then(setComments)
      .finally(() => setLoadingC(false))
  }, [districtId, start, end, sentiment])

  const downloadPdf = useCallback(async () => {
    setPdfLoading(true)
    try {
      const r = await api.downloadPdf(districtId, start, end)
      if (!r.ok) throw new Error('PDF error')
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `report_${districtId}.pdf`; a.click()
      URL.revokeObjectURL(url)
    } finally { setPdfLoading(false) }
  }, [districtId, start, end])

  if (!metrics) return (
    <div className="flex items-center justify-center h-full text-gray-400 text-sm">
      Выберите район на карте
    </div>
  )

  const delta = metrics.delta_vs_city * 100
  const scoreColor = metrics.negativity_score > 0.6 ? 'text-red-500' : metrics.negativity_score < 0.4 ? 'text-green-500' : 'text-yellow-500'

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      {/* Заголовок */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-800">{metrics.name_ru}</h2>
          <p className="text-sm text-gray-400">{metrics.total_posts.toLocaleString('ru')} сообщений</p>
        </div>
        <button onClick={downloadPdf} disabled={pdfLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-indigo-50 text-indigo-600 rounded-lg hover:bg-indigo-100 transition-colors disabled:opacity-50">
          {pdfLoading ? '…' : '↓ PDF'}
        </button>
      </div>

      {/* KPI карточки */}
      <div className="grid grid-cols-3 gap-3">
        <Kpi label="Негатив" value={`${(metrics.neg_share * 100).toFixed(1)}%`}
          sub={`${delta >= 0 ? '+' : ''}${delta.toFixed(1)} п.п.`}
          subColor={delta > 0 ? 'text-red-400' : 'text-green-400'} />
        <Kpi label="Score" value={metrics.negativity_score.toFixed(2)} valueColor={scoreColor} />
        <Kpi label="Активность" value={metrics.activity.toLocaleString('ru')} />
      </div>

      {/* Тональности pie-style */}
      <div className="bg-gray-50 rounded-xl p-3">
        <div className="flex gap-1 h-3 rounded-full overflow-hidden">
          <div className="bg-red-400 transition-all" style={{ width: `${metrics.neg_share * 100}%` }} />
          <div className="bg-gray-300 transition-all" style={{ width: `${(metrics.neutral / Math.max(metrics.total_posts, 1)) * 100}%` }} />
          <div className="bg-green-400 transition-all" style={{ width: `${(metrics.positive / Math.max(metrics.total_posts, 1)) * 100}%` }} />
        </div>
        <div className="flex justify-between text-xs text-gray-500 mt-1.5">
          <span>🔴 {metrics.negative}</span>
          <span>⚪ {metrics.neutral}</span>
          <span>🟢 {metrics.positive}</span>
        </div>
      </div>

      {/* График */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">Динамика</span>
          <div className="flex gap-1">
            {(['day', 'hour'] as const).map(b => (
              <button key={b} onClick={() => setBucket(b)}
                className={`text-xs px-2 py-0.5 rounded ${bucket === b ? 'bg-indigo-100 text-indigo-600' : 'text-gray-400 hover:text-gray-600'}`}>
                {b === 'day' ? 'День' : 'Час'}
              </button>
            ))}
          </div>
        </div>
        <SentimentChart data={timeseries} />
      </div>

      {/* Топ тем */}
      {topics.length > 0 && (
        <div>
          <p className="text-sm font-medium text-gray-700 mb-2">Топ темы</p>
          <div className="space-y-1.5">
            {topics.map(t => (
              <div key={t.topic_id} className="flex items-center gap-2 text-sm">
                <span className="flex-1 text-gray-700 truncate">{t.label || `Тема ${t.topic_id}`}</span>
                <span className="text-gray-400 text-xs">{t.count}</span>
                <span className={`text-xs ${t.neg_share > 0.3 ? 'text-red-400' : 'text-gray-400'}`}>
                  {(t.neg_share * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Комментарии */}
      <div>
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span className="text-sm font-medium text-gray-700">Комментарии</span>
          <div className="flex gap-1 ml-auto">
            {SENT_FILTERS.map(f => (
              <button key={f.value} onClick={() => setSentiment(f.value)}
                className={`text-xs px-2 py-0.5 rounded-full transition-colors
                  ${sentiment === f.value ? 'bg-indigo-100 text-indigo-600' : 'text-gray-400 hover:text-gray-600'}`}>
                {f.label}
              </button>
            ))}
          </div>
        </div>
        {loadingC ? <p className="text-gray-400 text-sm text-center py-4">Загрузка…</p>
          : <CommentList comments={comments} />}
      </div>
    </div>
  )
}

function Kpi({ label, value, sub, valueColor, subColor }: {
  label: string; value: string; sub?: string
  valueColor?: string; subColor?: string
}) {
  return (
    <div className="bg-white border border-gray-100 rounded-xl p-3 shadow-sm">
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      <p className={`text-xl font-bold ${valueColor ?? 'text-gray-800'}`}>{value}</p>
      {sub && <p className={`text-xs mt-0.5 ${subColor ?? 'text-gray-400'}`}>{sub}</p>}
    </div>
  )
}