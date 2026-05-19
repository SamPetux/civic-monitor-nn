import type {
  DataPeriod, DistrictMetrics, Comment,
  SentimentBucket, Topic, Burst, TopUser, RefreshStatus
} from './types'
import type { FeatureCollection } from 'geojson'

function qs(params: Record<string, string | number | null | undefined>) {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params))
    if (v != null && v !== '') p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: 'no-store' })
  if (!res.ok) throw new Error(`${res.status} ${url}`)
  return res.json()
}

export const api = {
  period:    () => get<DataPeriod>('/api/meta/period'),
  geoJson:   () => get<FeatureCollection>('/api/geo/districts'),
  metrics:   (start?: string|null, end?: string|null) =>
    get<DistrictMetrics[]>(`/api/districts/metrics${qs({ start, end })}`),
  comments:  (id: string, start?: string|null, end?: string|null, sentiment?: string|null, limit = 50) =>
    get<Comment[]>(`/api/districts/${id}/comments${qs({ start, end, sentiment, limit })}`),
  sentiment: (id: string, start?: string|null, end?: string|null, bucket = 'day') =>
    get<SentimentBucket[]>(`/api/districts/${id}/sentiment${qs({ start, end, bucket })}`),
  topics:    (id: string, start?: string|null, end?: string|null, limit = 5) =>
    get<Topic[]>(`/api/districts/${id}/topics${qs({ start, end, limit })}`),
  bursts:    (id: string, start?: string|null, end?: string|null, limit = 10) =>
    get<Burst[]>(`/api/districts/${id}/bursts${qs({ start, end, limit })}`),
  topUsers:  (start?: string|null, end?: string|null, limit = 30) =>
    get<TopUser[]>(`/api/users/top${qs({ start, end, limit })}`),
  refreshStatus: () => get<RefreshStatus>('/api/refresh/status'),
  refreshStart: (hours?: number, days?: number, max_posts = 50, skip_bursts = false) =>
    fetch('/api/refresh/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hours, days, max_posts, skip_bursts }),
    }).then(r => r.json()),
  refreshCancel: () => fetch('/api/refresh/cancel', { method: 'POST' }).then(r => r.json()),
  downloadPdf: (district_id: string|null, start: string, end: string) =>
    fetch('/api/reports/pdf', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ district_id, start, end }),
    }),
}