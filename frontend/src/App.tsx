import { Board } from '@/components/Board'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { ToastProvider } from '@/context/ToastContext'
import { ThemeProvider } from '@/context/ThemeContext'

function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <ToastProvider>
          <Board />
        </ToastProvider>
      </ThemeProvider>
    </ErrorBoundary>
  )
}

export default App
