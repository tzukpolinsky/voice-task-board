import React from 'react'
import { Settings, Moon, Sun, Loader } from 'lucide-react'
import { useTheme } from '@/context/ThemeContext'

interface BoardHeaderProps {
  pendingMirrorCount: number
  onOpenSettings: () => void
}

export const BoardHeader: React.FC<BoardHeaderProps> = ({ pendingMirrorCount, onOpenSettings }) => {
  const { theme, toggle } = useTheme()

  return (
    <div className="board-header">
      <h1 className="board-title">Voice Task Board</h1>
      <div className="board-header-right">
        {pendingMirrorCount > 0 && (
          <span className="pending-pill">
            <Loader size={14} />
            {pendingMirrorCount} pending sync
          </span>
        )}
        <button
          onClick={toggle}
          className="theme-toggle"
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
        >
          {theme === 'dark' ? <Moon size={18} /> : <Sun size={18} />}
        </button>
        <button
          onClick={onOpenSettings}
          className="settings-btn"
          title="Settings"
        >
          <Settings size={18} />
        </button>
      </div>
    </div>
  )
}
