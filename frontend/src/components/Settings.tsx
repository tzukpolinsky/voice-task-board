import React, { useState, useRef } from 'react'
import { Cloud, Link } from 'lucide-react'
import type { Category } from '@/types/domain'
import { api } from '@/api'

// ── Remote provider section ──────────────────────────────────────────────────

const RemoteSection: React.FC<{ provider: string | null; onChanged: () => void }> = ({ provider, onChanged }) => {
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleConnect = async (p: string) => {
    setConnecting(true)
    setError(null)
    try {
      const result = await api.connectRemoteProvider(p)
      if (result.ok) {
        onChanged()
      } else {
        setError(result.error ?? 'Connection failed')
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setConnecting(false)
    }
  }

  const handleDisconnect = async () => {
    await api.disconnectRemoteProvider()
    onChanged()
  }

  return (
    <div style={{ marginBottom: '16px' }}>
      <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500 }}>Remote Reminders</label>
      {provider ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px', background: 'var(--color-success-bg)', borderRadius: '4px', fontSize: '13px' }}>
          <span style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '6px' }}><Cloud size={16} /> Connected to <strong>Google Tasks</strong></span>
          <button
            onClick={handleDisconnect}
            style={{ padding: '4px 10px', background: 'var(--color-danger-strong)', color: 'var(--color-surface)', border: 'none', borderRadius: '3px', cursor: 'pointer', fontSize: '12px' }}
          >
            Disconnect
          </button>
        </div>
      ) : (
        <div>
          <p style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginBottom: '8px' }}>
            Mirror tasks to Google Tasks so they appear on your phone.
          </p>
          <button
            onClick={() => handleConnect('google')}
            disabled={connecting}
            style={{ width: '100%', padding: '10px', background: '#4285F4', color: 'var(--color-surface)', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '13px', fontWeight: 500, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
          >
            <Link size={16} /> {connecting ? 'Opening browser...' : 'Connect Google Tasks'}
          </button>
          {error && <p style={{ marginTop: '6px', fontSize: '12px', color: 'var(--color-danger-strong)' }}>{error}</p>}
        </div>
      )}
    </div>
  )
}

interface SettingsProps {
  isOpen: boolean
  onClose: () => void
  onConfigChanged: () => void
}

const MODIFIER_KEYS = new Set(['Control', 'Shift', 'Alt', 'Meta'])

const formatKey = (key: string): string => {
  if (key === ' ' || key === 'Spacebar') return 'space'
  if (key.length === 1) return key.toLowerCase()
  return key.toLowerCase()
}

const HotkeyCapture: React.FC<{ value: string; onChange: (v: string) => void }> = ({ value, onChange }) => {
  const [capturing, setCapturing] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    e.preventDefault()
    e.stopPropagation()

    if (e.key === 'Escape') {
      setCapturing(false)
      inputRef.current?.blur()
      return
    }

    if (MODIFIER_KEYS.has(e.key)) return

    const parts: string[] = []
    if (e.ctrlKey) parts.push('ctrl')
    if (e.shiftKey) parts.push('shift')
    if (e.altKey) parts.push('alt')
    if (e.metaKey) parts.push('meta')
    parts.push(formatKey(e.key))

    onChange(parts.join('+'))
    setCapturing(false)
    inputRef.current?.blur()
  }

  return (
    <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
      <input
        ref={inputRef}
        type="text"
        readOnly
        value={capturing ? 'Press keys...' : value}
        onFocus={() => setCapturing(true)}
        onBlur={() => setCapturing(false)}
        onKeyDown={handleKeyDown}
        placeholder="Click to set shortcut"
        style={{
          flex: 1,
          padding: '8px',
          border: capturing ? '2px solid var(--color-accent)' : '1px solid var(--color-border-strong)',
          borderRadius: '4px',
          background: capturing ? 'var(--color-accent-bg)' : 'var(--color-surface)',
          cursor: 'pointer',
          fontFamily: 'monospace',
        }}
      />
      <button
        onClick={() => inputRef.current?.focus()}
        style={{
          padding: '8px 12px',
          background: 'var(--color-accent)',
          color: 'var(--color-surface)',
          border: 'none',
          borderRadius: '4px',
          cursor: 'pointer',
          fontSize: '12px',
        }}
      >
        {capturing ? 'Listening' : 'Record'}
      </button>
    </div>
  )
}

export const Settings: React.FC<SettingsProps> = ({ isOpen, onClose, onConfigChanged }) => {
  const [apiKey, setApiKey] = useState('')
  const [hotkey, setHotkey] = useState('ctrl+shift+space')
  const [newCategory, setNewCategory] = useState('')
  const [categories, setCategories] = useState<Category[]>([])
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<string | null>(null)
  const [remoteProvider, setRemoteProvider] = useState<string | null>(null)
  const [encryptionUnavailable, setEncryptionUnavailable] = useState(false)

  React.useEffect(() => {
    if (isOpen) {
      loadConfig()
    }
  }, [isOpen])

  const loadConfig = async () => {
    try {
      const pywebview = window.pywebview
      if (pywebview?.api.get_config) {
        const config = await pywebview.api.get_config()
        if (config) {
          setApiKey(config.gemini_api_key || '')
          setHotkey(config.hotkey || 'ctrl+shift+space')
          setRemoteProvider(config.remote_provider ?? null)
          setEncryptionUnavailable(Boolean(config.encryption_unavailable))
        }
      }
      const cats = await api.getCategories()
      setCategories(cats || [])
    } catch (e) {
      console.error('Failed to load config', e)
    }
  }

  const handleSave = async () => {
    try {
      const pywebview = window.pywebview
      if (pywebview?.api.save_config) {
        await pywebview.api.save_config(apiKey, hotkey)
      }
      onConfigChanged()

      // save_config may have failed to encrypt (DPAPI unavailable). Re-read the
      // flag: if secrets weren't persisted, keep the panel open and show the
      // warning instead of silently closing as though the save succeeded.
      let encFailed = false
      if (pywebview?.api.get_config) {
        const fresh = await pywebview.api.get_config()
        encFailed = Boolean(fresh?.encryption_unavailable)
        setEncryptionUnavailable(encFailed)
      }
      if (!encFailed) {
        onClose()
      }
    } catch (e) {
      console.error('Failed to save config', e)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const pywebview = window.pywebview
      const result = pywebview?.api.test_gemini_key ? await pywebview.api.test_gemini_key(apiKey) : false
      setTestResult(result ? 'API key is valid (OK)' : 'API key is invalid (FAIL)')
    } catch (e) {
      setTestResult(`Error: ${String(e).slice(0, 50)}`)
    } finally {
      setTesting(false)
    }
  }

  const handleAddCategory = async () => {
    if (!newCategory.trim()) return
    try {
      await api.addCategory(newCategory)
      setNewCategory('')
      loadConfig()
    } catch (e) {
      console.error('Failed to add category', e)
    }
  }

  const handleDeleteCategory = async (categoryId: number) => {
    try {
      await api.deleteCategory(categoryId)
      loadConfig()
    } catch (e) {
      console.error('Failed to delete category', e)
    }
  }

  if (!isOpen) return null

  return (
    <div className="settings-overlay">
      <div className="settings-panel">
        <h2 style={{ marginBottom: '16px' }}>Settings</h2>

        {encryptionUnavailable && (
          <div
            role="alert"
            style={{
              marginBottom: '16px',
              padding: '10px 12px',
              background: 'var(--color-danger-bg, #3a1212)',
              border: '1px solid var(--color-danger-strong)',
              borderRadius: '4px',
              fontSize: '12px',
              color: 'var(--color-danger-strong)',
            }}
          >
            <strong>Secrets could not be saved securely.</strong> Windows
            encryption (DPAPI) is unavailable, so your API key and remote
            connection were <em>not</em> stored — to avoid writing them to disk
            in plain text. They will need to be re-entered next time the app
            starts. If this persists, check that the app has access to Windows
            Data Protection.
          </div>
        )}

        <div className="settings-row">
          <label className="settings-label">API Key</label>
          <input
            className="settings-input"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            style={{
              fontFamily: 'monospace',
              fontSize: '12px',
            }}
          />
          <button
            onClick={handleTest}
            disabled={testing}
            style={{
              marginTop: '8px',
              padding: '6px 12px',
              background: 'var(--color-success)',
              color: 'var(--color-surface)',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '12px',
            }}
          >
            {testing ? 'Testing...' : 'Test Connection'}
          </button>
          {testResult && (
            <p style={{ marginTop: '4px', fontSize: '12px', color: testResult.includes('valid') ? 'var(--color-success)' : 'var(--color-danger-strong)' }}>
              {testResult}
            </p>
          )}
        </div>

        <div className="settings-row">
          <label className="settings-label">Hotkey</label>
          <HotkeyCapture value={hotkey} onChange={setHotkey} />
          <p style={{ marginTop: '4px', fontSize: '11px', color: 'var(--color-text-tertiary)' }}>
            Click the field, then press the key combination you want (e.g. Ctrl+Shift+Z).
          </p>
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500 }}>Categories</label>
          <div style={{ marginBottom: '8px' }}>
            {categories.map((cat) => (
              <div key={cat.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px', background: 'var(--color-bg-secondary)', borderRadius: '3px', marginBottom: '4px', fontSize: '12px' }}>
                <span>{cat.name}</span>
                {cat.id !== 1 && (
                  <button
                    onClick={() => handleDeleteCategory(cat.id)}
                    style={{
                      padding: '2px 6px',
                      background: 'var(--color-danger-strong)',
                      color: 'var(--color-surface)',
                      border: 'none',
                      borderRadius: '3px',
                      cursor: 'pointer',
                      fontSize: '11px',
                    }}
                  >
                    Remove
                  </button>
                )}
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: '4px' }}>
            <input
              type="text"
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
              placeholder="New category"
              style={{
                flex: 1,
                padding: '6px',
                border: '1px solid var(--color-border-strong)',
                borderRadius: '4px',
                fontSize: '12px',
              }}
            />
            <button
              onClick={handleAddCategory}
              style={{
                padding: '6px 12px',
                background: 'var(--color-accent)',
                color: 'var(--color-surface)',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '12px',
              }}
            >
              Add
            </button>
          </div>
        </div>

        <RemoteSection provider={remoteProvider} onChanged={loadConfig} />

        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            className="btn-secondary"
            style={{
              padding: '8px 16px',
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="btn-primary"
            style={{
              padding: '8px 16px',
              background: 'var(--color-accent)',
              color: 'var(--color-surface)',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  )
}
