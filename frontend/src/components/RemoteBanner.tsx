import React from 'react'
import { Cloud, X } from 'lucide-react'

interface RemoteBannerProps {
  pendingCount: number
  onConnect: () => void
  onDismiss: () => void
}

export const RemoteBanner: React.FC<RemoteBannerProps> = ({ pendingCount, onConnect, onDismiss }) => (
  <div className="remote-banner" style={{
    background: 'var(--color-primary-soft)',
    border: '1px solid var(--color-border)',
    borderRadius: 'var(--radius-md)',
    padding: 'var(--space-2) var(--space-4)',
    marginBottom: 'var(--space-3)',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 'var(--space-3)',
    fontSize: 'var(--text-base)',
    color: 'var(--color-primary-hover)',
  }}>
    <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
      <Cloud size={14} /> Connect Google Tasks or Microsoft To Do to mirror tasks to your phone.
      {pendingCount > 0 && <strong> ({pendingCount} pending sync)</strong>}
    </span>
    <div style={{ display: 'flex', gap: 'var(--space-2)', flexShrink: 0 }}>
      <button onClick={onConnect} style={{ padding: 'var(--space-1) var(--space-3)', background: 'var(--color-primary)', color: 'var(--color-surface)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: 'var(--text-sm)' }}>
        Connect
      </button>
      <button onClick={onDismiss} style={{ padding: 'var(--space-1) var(--space-2)', background: 'transparent', color: 'var(--color-text-tertiary)', border: 'none', cursor: 'pointer', fontSize: 'var(--text-lg)', display: 'flex', alignItems: 'center' }}>
        <X size={16} />
      </button>
    </div>
  </div>
)
