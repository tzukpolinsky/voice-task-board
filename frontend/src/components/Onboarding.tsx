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
    if (window.pywebview?.api?.open_url) {
      window.pywebview.api.open_url('https://aistudio.google.com/apikey')
    } else {
      window.open('https://aistudio.google.com/apikey', '_blank')
    }
  }

  if (!isOpen) return null

  return (
    <div className="onboarding">
      <h1>Welcome to Voice Task Board</h1>
      <div style={{ textAlign: 'left', maxWidth: '440px' }}>
        <p style={{ marginBottom: '24px' }}>
          To get started, you need a Gemini API key. Get one free at{' '}
          <button
            onClick={handleOpenApiUrl}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--color-primary)',
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

        <div style={{ marginBottom: '20px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500 }}>Paste your API key:</label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="AIza..."
            style={{
              width: '100%',
              padding: '12px',
              border: '1px solid var(--color-border-strong)',
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
            background: 'var(--color-success)',
            color: 'var(--color-surface)',
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
            color: testResult.includes('valid') ? 'var(--color-success)' : 'var(--color-danger)',
          }}>
            {testResult}
          </p>
        )}

        <button
          onClick={handleComplete}
          disabled={!apiKey.trim()}
          className="onboarding-btn btn-primary"
          style={{
            padding: '12px 24px',
            width: '100%',
          }}
        >
          Get Started
        </button>
      </div>
    </div>
  )
}
