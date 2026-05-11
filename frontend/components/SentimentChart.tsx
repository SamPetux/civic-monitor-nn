'use client'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import type { SentimentBucket } from '@/lib/types'

const COLORS = { negative: '#e74c3c', neutral: '#95a5a6', positive: '#2ecc71' }

export default function SentimentChart({ data }: { data: SentimentBucket[] }) {
  if (!data.length) return <p className="text-gray-400 text-sm py-4 text-center">Нет данных</p>

  const formatted = data.map(d => ({
    ...d,
    date: d.date.length > 10 ? d.date.slice(5, 16) : d.date.slice(5),
  }))

  return (
    <ResponsiveContainer width="100%" height={180}>
      <AreaChart data={formatted} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
        <XAxis dataKey="date" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
        <Tooltip
          contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
          labelStyle={{ fontWeight: 600 }}
        />
        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />
        <Area dataKey="negative" name="Негатив" stackId="1" stroke={COLORS.negative} fill={COLORS.negative} fillOpacity={0.7} />
        <Area dataKey="neutral"  name="Нейтрал" stackId="1" stroke={COLORS.neutral}  fill={COLORS.neutral}  fillOpacity={0.5} />
        <Area dataKey="positive" name="Позитив" stackId="1" stroke={COLORS.positive} fill={COLORS.positive} fillOpacity={0.7} />
      </AreaChart>
    </ResponsiveContainer>
  )
}