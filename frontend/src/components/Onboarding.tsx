import React, { useState } from 'react'

interface OnboardingProps {
  isOpen: boolean
  onComplete: () => void
}

export const Onboarding: React.FC<OnboardingProps> = ({ isOpen, onComplete }) => {
  const [apiKey, setApiKey] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<string | null>(null)

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const api = window.pywebview?.api
      const result = api ? await api.test_gemini_key(apiKey) : false
      setTestResult(result ? 'API key is valid (OK)' : 'API key is invalid (FAIL)')
    } catch (e) {
      setTestResult(`Error: ${String(e).slice(0, 50)}`)
    } finally {
      setTesting(false)
    }
  }

  const handleComplete = async () => {
    if (!apiKey.trim()) {
      setTestResult('Please enter an API key')
      return
    }
    try {
      const api = window.pywebview?.api
      if (api) {
        await api.save_config(apiKey, 'ctrl+shift+space')
      }
      onComplete()
    } catch (e) {
      setTestResult(`Error: ${String(e).slice(0, 50)}`)
    }
  }

  const handleOpenApiUrl = () => {
    const webview = (window as any).pywebview
    if (webview?.api?.open_url) {
      webview.api.open_url('https://aistudio.google.com/apikey')
    } else {
      window.open('https://aistudio.google.com/apikey', '_blank')
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
      background: '#f5f5f5',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 2000,
    }}>
      <div style={{
        background: '#fff',
        borderRadius: '8px',
        padding: '40px',
        maxWidth: '500px',
        textAlign: 'center',
        boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
      }}>
        <h1 style={{ marginBottom: '16px', fontSize: '28px' }}>Welcome to Voice Task Board</h1>
        <p style={{ marginBottom: '24px', color: '#666' }}>
          To get started, you need a Gemini API key. Get one free at{' '}
          <button
            onClick={handleOpenApiUrl}
            style={{
              background: 'none',
              border: 'none',
              color: '#2196F3',
              textDecoration: 'underline',
              cursor: 'pointer',
              fontSize: 'inherit',
              padding: 0,
              fontFamily: 'inherit',
            }}
          >
            aistudio.google.com/apikey
          </button>
        </p>

        <div style={{ marginBottom: '20px', textAlign: 'left' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500 }}>Paste your API key:</label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="AIza..."
            style={{
              width: '100%',
              padding: '12px',
              border: '1px solid #ddd',
              borderRadius: '4px',
              fontFamily: 'monospace',
              fontSize: '12px',
            }}
          />
        </div>

        <button
          onClick={handleTest}
          disabled={testing}
          style={{
            marginBottom: '16px',
            padding: '10px 20px',
            background: '#4CAF50',
            color: '#fff',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontSize: '14px',
            fontWeight: 500,
          }}
        >
          {testing ? 'Testing...' : 'Test Connection'}
        </button>

        {testResult && (
          <p style={{
            marginBottom: '16px',
            fontSize: '14px',
            color: testResult.includes('valid') ? '#4CAF50' : '#f44',
          }}>
            {testResult}
          </p>
        )}

        <button
          onClick={handleComplete}
          disabled={!apiKey.trim()}
          style={{
            padding: '12px 24px',
            background: '#2196F3',
            color: '#fff',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontSize: '14px',
            fontWeight: 500,
            opacity: apiKey.trim() ? 1 : 0.5,
          }}
        >
          Get Started
        </button>
      </div>
    </div>
  )
}
