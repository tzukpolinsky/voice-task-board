import React, { createContext, useContext, useMemo } from 'react'
import { useErrorToast as useErrorToastHook } from '@/hooks/useErrorToast'
import { ErrorToast } from '@/components/ErrorToast'

interface ToastContextType {
  message: string | null
  show: (message: string) => void
  dismiss: () => void
}

const ToastContext = createContext<ToastContextType | undefined>(undefined)

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const toast = useErrorToastHook()
  
  // Memoize the context value to ensure referential stability
  const contextValue = useMemo(
    () => ({ message: toast.message, show: toast.show, dismiss: toast.dismiss }),
    [toast.message, toast.show, toast.dismiss]
  )

  return (
    <ToastContext.Provider value={contextValue}>
      {children}
      <ErrorToast message={toast.message} onDismiss={toast.dismiss} />
    </ToastContext.Provider>
  )
}

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used within ToastProvider')
  }
  return context
}
