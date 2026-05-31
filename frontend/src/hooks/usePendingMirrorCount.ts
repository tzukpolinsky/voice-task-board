import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api'

export function usePendingMirrorCount() {
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refetch = useCallback(async () => {
    try {
      const data = await api.getPendingMirrorCount()
      setCount(data ?? 0)
      setError(null)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { count, loading, error, refetch }
}
