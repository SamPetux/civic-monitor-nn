'use client'
import { useEffect, useRef } from 'react'
import type { Map, MapMouseEvent, GeoJSONSource } from 'maplibre-gl'
import type { DistrictMetrics } from '@/lib/types'
import type { FeatureCollection } from 'geojson'

// Цветовая шкала совпадает с visualization.py
const COLOR_EXPR = [
  'interpolate', ['linear'], ['get', 'negativity_score'],
  0.0,  '#2ecc71',
  0.25, '#a3d977',
  0.5,  '#f1c40f',
  0.75, '#e67e22',
  1.0,  '#e74c3c',
] as unknown as maplibregl.ExpressionSpecification

interface Props {
  geojson: FeatureCollection
  metrics: DistrictMetrics[]
  selectedId: string | null
  onSelect: (id: string) => void
}

export default function DistrictMap({ geojson, metrics, selectedId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<Map | null>(null)

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    // Импортируем maplibre-gl только в браузере
    import('maplibre-gl').then(({ default: maplibregl }) => {
      const map = new maplibregl.Map({
        container: containerRef.current!,
        style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
        center: [43.936, 56.296],   // Нижний Новгород
        zoom: 11,
        attributionControl: false,
      })
      mapRef.current = map

      map.on('load', () => {
        // Обогащаем GeoJSON метриками
        const metricsMap = new Map(metrics.map(m => [m.district_id, m]))
        const enriched: FeatureCollection = {
          ...geojson,
          features: geojson.features.map(f => ({
            ...f,
            properties: {
              ...f.properties,
              ...metricsMap.get(f.properties?.id ?? f.properties?.district_id ?? ''),
            },
          })),
        }

        map.addSource('districts', { type: 'geojson', data: enriched })

        // Заливка по negativity_score
        map.addLayer({
          id: 'districts-fill',
          type: 'fill',
          source: 'districts',
          paint: {
            'fill-color': COLOR_EXPR,
            'fill-opacity': ['case', ['==', ['get', 'district_id'], selectedId ?? ''], 0.85, 0.65],
          },
        })

        // Обводка
        map.addLayer({
          id: 'districts-outline',
          type: 'line',
          source: 'districts',
          paint: {
            'line-color': ['case', ['==', ['get', 'district_id'], selectedId ?? ''], '#1e3a5f', '#ffffff'],
            'line-width': ['case', ['==', ['get', 'district_id'], selectedId ?? ''], 3, 1],
          },
        })

        // Тултип
        const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false })
        map.on('mousemove', 'districts-fill', (e: MapMouseEvent & { features?: maplibregl.MapGeoJSONFeature[] }) => {
          if (!e.features?.length) return
          map.getCanvas().style.cursor = 'pointer'
          const p = e.features[0].properties
          popup.setLngLat(e.lngLat).setHTML(`
            <div style="font-family:sans-serif;font-size:13px;min-width:160px">
              <div style="font-weight:600;margin-bottom:4px">${p.name_ru ?? p.district_id}</div>
              <div>Сообщений: <b>${p.total_posts ?? '—'}</b></div>
              <div>Негатив: <b>${p.neg_share != null ? (p.neg_share * 100).toFixed(1) + '%' : '—'}</b></div>
              <div>Score: <b>${p.negativity_score != null ? p.negativity_score.toFixed(2) : '—'}</b></div>
            </div>
          `).addTo(map)
        })
        map.on('mouseleave', 'districts-fill', () => {
          map.getCanvas().style.cursor = ''
          popup.remove()
        })

        // Клик по району
        map.on('click', 'districts-fill', (e: MapMouseEvent & { features?: maplibregl.MapGeoJSONFeature[] }) => {
          if (!e.features?.length) return
          const id = e.features[0].properties?.district_id
          if (id) onSelect(id)
        })
      })
    })

    return () => { mapRef.current?.remove(); mapRef.current = null }
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  // Обновляем подсветку выбранного района без пересоздания карты
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.isStyleLoaded()) return
    map.setPaintProperty('districts-fill', 'fill-opacity',
      ['case', ['==', ['get', 'district_id'], selectedId ?? ''], 0.85, 0.65])
    map.setPaintProperty('districts-outline', 'line-color',
      ['case', ['==', ['get', 'district_id'], selectedId ?? ''], '#1e3a5f', '#ffffff'])
    map.setPaintProperty('districts-outline', 'line-width',
      ['case', ['==', ['get', 'district_id'], selectedId ?? ''], 3, 1])
  }, [selectedId])

  // Обновляем данные при смене метрик
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.isStyleLoaded()) return
    const metricsMap = new Map(metrics.map(m => [m.district_id, m]))
    const enriched: FeatureCollection = {
      ...geojson,
      features: geojson.features.map(f => ({
        ...f,
        properties: {
          ...f.properties,
          ...metricsMap.get(f.properties?.id ?? f.properties?.district_id ?? ''),
        },
      })),
    }
    ;(map.getSource('districts') as GeoJSONSource | undefined)?.setData(enriched)
  }, [metrics, geojson])

  return <div ref={containerRef} className="w-full h-full" />
}