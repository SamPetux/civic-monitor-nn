'use client'
import { useRouter, useSearchParams, usePathname } from 'next/navigation'
import { useCallback, useMemo } from 'react'
import { format, subDays } from 'date-fns'

const fmt = (d: Date) => format(d, "yyyy-MM-dd'T'HH:mm:ss")

function defaults() {
  const now = new Date()
  return {
    start: fmt(new Date(now.getTime() - 30 * 86400_000)),
    end: fmt(now),
  }
}

export function usePeriod() {
  const router = useRouter()
  const pathname = usePathname()
  const params = useSearchParams()

  const { start, end } = useMemo(() => {
    const d = defaults()
    return {
      start: params.get('start') ?? d.start,
      end: params.get('end') ?? d.end,
    }
  }, [params])

  const setPeriod = useCallback(
    (newStart: string, newEnd: string) => {
      const p = new URLSearchParams(params.toString())
      p.set('start', newStart)
      p.set('end', newEnd)
      router.replace(`${pathname}?${p.toString()}`, { scroll: false })
    },
    [router, pathname, params]
  )

  return { start, end, setPeriod }
}
