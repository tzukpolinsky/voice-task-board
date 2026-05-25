import React, { useState, useRef } from 'react'
import { api, Category } from '../api'

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
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px', background: '#e8f5e9', borderRadius: '4px', fontSize: '13px' }}>
          <span style={{ flex: 1 }}>☁ Connected to <strong>Google Tasks</strong></span>
          <button
            onClick={handleDisconnect}
            style={{ padding: '4px 10px', background: '#ff4444', color: '#fff', border: 'none', borderRadius: '3px', cursor: 'pointer', fontSize: '12px' }}
          >
            Disconnect
          </button>
        </div>
      ) : (
        <div>
          <p style={{ fontSize: '12px', color: '#666', marginBottom: '8px' }}>
            Mirror tasks to Google Tasks so they appear on your phone.
          </p>
          <button
            onClick={() => handleConnect('google')}
            disabled={connecting}
            style={{ width: '100%', padding: '10px', background: '#4285F4', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '13px', fontWeight: 500 }}
          >
            {connecting ? 'Opening browser...' : '🔗 Connect Google Tasks'}
          </button>
          {error && <p style={{ marginTop: '6px', fontSize: '12px', color: '#f44' }}>{error}</p>}
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
          border: capturing ? '2px solid #2196F3' : '1px solid #ddd',
          borderRadius: '4px',
          background: capturing ? '#e3f2fd' : '#fff',
          cursor: 'pointer',
          fontFamily: 'monospace',
        }}
      />
      <button
        onClick={() => inputRef.current?.focus()}
        style={{
          padding: '8px 12px',
          background: '#2196F3',
          color: '#fff',
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
        setApiKey(config.gemini_api_key || '')
        setHotkey(config.hotkey || 'ctrl+shift+space')
        setRemoteProvider(config.remote_provider ?? null)
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
      onClose()
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
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0,0,0,0.5)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
    }}>
      <div style={{
        background: '#fff',
        borderRadius: '8px',
        padding: '20px',
        maxWidth: '500px',
        maxHeight: '80vh',
        overflow: 'auto',
        boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
      }}>
        <h2 style={{ marginBottom: '16px' }}>Settings</h2>

        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'block', marginBottom: '4px', fontWeight: 500 }}>API Key</label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            style={{
              width: '100%',
              padding: '8px',
              border: '1px solid #ddd',
              borderRadius: '4px',
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
              background: '#4CAF50',
              color: '#fff',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '12px',
            }}
          >
            {testing ? 'Testing...' : 'Test Connection'}
          </button>
          {testResult && (
            <p style={{ marginTop: '4px', fontSize: '12px', color: testResult.includes('valid') ? '#4CAF50' : '#f44' }}>
              {testResult}
            </p>
          )}
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'block', marginBottom: '4px', fontWeight: 500 }}>Hotkey</label>
          <HotkeyCapture value={hotkey} onChange={setHotkey} />
          <p style={{ marginTop: '4px', fontSize: '11px', color: '#888' }}>
            Click the field, then press the key combination you want (e.g. Ctrl+Shift+Z).
          </p>
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500 }}>Categories</label>
          <div style={{ marginBottom: '8px' }}>
            {categories.map((cat) => (
              <div key={cat.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px', background: '#f0f0f0', borderRadius: '3px', marginBottom: '4px', fontSize: '12px' }}>
                <span>{cat.name}</span>
                {cat.id !== 1 && (
                  <button
                    onClick={() => handleDeleteCategory(cat.id)}
                    style={{
                      padding: '2px 6px',
                      background: '#ff4444',
                      color: '#fff',
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
                border: '1px solid #ddd',
                borderRadius: '4px',
                fontSize: '12px',
              }}
            />
            <button
              onClick={handleAddCategory}
              style={{
                padding: '6px 12px',
                background: '#2196F3',
                color: '#fff',
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
            style={{
              padding: '8px 16px',
              background: '#ccc',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            style={{
              padding: '8px 16px',
              background: '#2196F3',
              color: '#fff',
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
