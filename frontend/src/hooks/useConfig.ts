import { useCallback, useEffect, useState } from 'react'
import type { Config } from '@/types/domain'

export function useConfig() {
  const [config, setConfig] = useState<Config | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refetch = useCallback(async () => {
    try {
      const data = await (window.pywebview?.api.get_config?.() ?? Promise.resolve(null))
      setConfig(data)
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

  return { config, loading, error, refetch }
}
