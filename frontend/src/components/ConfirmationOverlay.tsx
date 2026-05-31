import React, { useEffect, useState } from 'react'
import { Folder, Clock, Cloud, Check, Pencil, X } from 'lucide-react'
import type { ConfirmationPayload } from '@/types/domain'

interface ConfirmationOverlayProps {
  payload: ConfirmationPayload
  onAction: (action: 'accept' | 'edit' | 'cancel') => void
}

const overlayBtn = (bg: string, color: string): React.CSSProperties => ({
  flex: 1,
  padding: 'var(--space-1) var(--space-1)',
  background: bg,
  color,
  border: 'none',
  borderRadius: 'var(--radius-md)',
  cursor: 'pointer',
  fontSize: 'var(--text-sm)',
  fontWeight: 600,
})

export const ConfirmationOverlay: React.FC<ConfirmationOverlayProps> = ({ payload, onAction }) => {
  const [countdown, setCountdown] = useState(payload.timeout)

  useEffect(() => {
    if (countdown <= 0) {
      onAction('accept')
      return
    }
    const t = setTimeout(() => setCountdown(c => c - 1), 1000)
    return () => clearTimeout(t)
  }, [countdown, onAction])

  return (
    <div className="confirmation-overlay" style={{
      position: 'fixed',
      bottom: 'var(--space-5)',
      right: 'var(--space-5)',
      background: 'transparent',
      border: 'none',
      borderRadius: 'var(--radius-lg)',
      padding: 0,
      boxShadow: 'none',
      zIndex: 2000,
      inset: 'unset',
      minWidth: '280px',
      maxWidth: '360px',
      display: 'flex',
      alignItems: 'unset',
      justifyContent: 'unset',
    }}>
      <div className="confirmation-overlay-content" style={{
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border-strong)',
        borderRadius: 'var(--radius-lg)',
        padding: 'var(--space-4) var(--space-5)',
        boxShadow: 'var(--shadow-overlay)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-2)' }}>
          <strong style={{ fontSize: 'var(--text-base)' }}>New task</strong>
          <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-tertiary)' }}>auto-accept in {countdown}s</span>
        </div>
        <p className="confirmation-text" style={{ fontWeight: 600, fontSize: 'var(--text-md)', marginBottom: 'var(--space-1)', wordBreak: 'break-word' }}>{payload.title}</p>
        <div style={{ display: 'flex', gap: 'var(--space-2)', fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)', marginBottom: 'var(--space-3)', flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Folder size={14} /> {payload.category}</span>
          {payload.due && <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Clock size={14} /> {payload.due}</span>}
          {payload.mirror && <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Cloud size={14} /> Remote</span>}
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
          <button onClick={() => onAction('accept')} style={overlayBtn('var(--color-success)', 'var(--color-surface)')} title="Accept"><Check size={16} style={{ marginRight: '4px' }} /> Accept</button>
          <button onClick={() => onAction('edit')} style={overlayBtn('var(--color-primary)', 'var(--color-surface)')} title="Edit"><Pencil size={16} style={{ marginRight: '4px' }} /> Edit</button>
          <button onClick={() => onAction('cancel')} style={overlayBtn('var(--color-danger)', 'var(--color-surface)')} title="Cancel"><X size={16} style={{ marginRight: '4px' }} /> Cancel</button>
        </div>
      </div>
    </div>
  )
}
