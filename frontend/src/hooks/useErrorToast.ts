import { useCallback, useState } from 'react'

export function useErrorToast() {
  const [message, setMessage] = useState<string | null>(null)

  const show = useCallback((msg: string) => {
    setMessage(msg)
  }, [])

  const dismiss = useCallback(() => {
    setMessage(null)
  }, [])

  return { message, show, dismiss }
}
