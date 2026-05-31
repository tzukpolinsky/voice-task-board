import React from 'react'
import { X } from 'lucide-react'

interface ErrorToastProps {
  message: string | null
  onDismiss: () => void
}

export const ErrorToast: React.FC<ErrorToastProps> = ({ message, onDismiss }) => {
  React.useEffect(() => {
    if (message) {
      const timeout = setTimeout(onDismiss, 4000)
      return () => clearTimeout(timeout)
    }
  }, [message, onDismiss])

  if (!message) return null

  return (
    <div className="error-toast">
      <span>{message}</span>
      <button
        className="error-toast-close"
        onClick={onDismiss}
        style={{
          display: 'flex',
          alignItems: 'center',
        }}
      >
        <X size={18} />
      </button>
    </div>
  )
}
