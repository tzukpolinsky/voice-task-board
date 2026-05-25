import React, { useEffect, useState } from 'react'
import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { Task, Category, ConfirmationPayload, api } from '../api'
import { Column } from './Column'
import { Settings } from './Settings'
import { Onboarding } from './Onboarding'

// ── Confirmation overlay ────────────────────────────────────────────────────

const ConfirmationOverlay: React.FC<{
  payload: ConfirmationPayload
  onAction: (action: 'accept' | 'edit' | 'cancel') => void
}> = ({ payload, onAction }) => {
  const [countdown, setCountdown] = useState(payload.timeout)

  useEffect(() => {
    if (countdown <= 0) {
      onAction('accept')
      return
    }
    const t = setTimeout(() => setCountdown(c => c - 1), 1000)
    return () => clearTimeout(t)
  }, [countdown])

  return (
    <div style={{
      position: 'fixed',
      bottom: '24px',
      right: '24px',
      background: '#fff',
      border: '1px solid #ddd',
      borderRadius: '8px',
      padding: '16px 20px',
      boxShadow: '0 4px 16px rgba(0,0,0,0.18)',
      zIndex: 2000,
      minWidth: '280px',
      maxWidth: '360px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <strong style={{ fontSize: '13px' }}>New task</strong>
        <span style={{ fontSize: '12px', color: '#aaa' }}>auto-accept in {countdown}s</span>
      </div>
      <p style={{ fontWeight: 600, fontSize: '14px', marginBottom: '4px', wordBreak: 'break-word' }}>{payload.title}</p>
      <div style={{ display: 'flex', gap: '8px', fontSize: '12px', color: '#666', marginBottom: '12px', flexWrap: 'wrap' }}>
        <span>📁 {payload.category}</span>
        {payload.due && <span>⏰ {payload.due}</span>}
        {payload.mirror && <span>☁ Remote</span>}
      </div>
      <div style={{ display: 'flex', gap: '8px' }}>
        <button onClick={() => onAction('accept')} style={overlayBtn('#4CAF50', '#fff')}>✓ Accept</button>
        <button onClick={() => onAction('edit')} style={overlayBtn('#2196F3', '#fff')}>✎ Edit</button>
        <button onClick={() => onAction('cancel')} style={overlayBtn('#ff4444', '#fff')}>✕ Cancel</button>
      </div>
    </div>
  )
}

const overlayBtn = (bg: string, color: string): React.CSSProperties => ({
  flex: 1,
  padding: '6px 4px',
  background: bg,
  color,
  border: 'none',
  borderRadius: '4px',
  cursor: 'pointer',
  fontSize: '12px',
  fontWeight: 600,
})

// ── Remote banner ────────────────────────────────────────────────────────────

const RemoteBanner: React.FC<{
  pendingCount: number
  onConnect: () => void
  onDismiss: () => void
}> = ({ pendingCount, onConnect, onDismiss }) => (
  <div style={{
    background: '#e3f2fd',
    border: '1px solid #90caf9',
    borderRadius: '4px',
    padding: '10px 16px',
    marginBottom: '12px',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: '12px',
    fontSize: '13px',
  }}>
    <span>
      ☁ Connect Google Tasks or Microsoft To Do to mirror tasks to your phone.
      {pendingCount > 0 && <strong> ({pendingCount} pending sync)</strong>}
    </span>
    <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
      <button onClick={onConnect} style={{ padding: '4px 12px', background: '#2196F3', color: '#fff', border: 'none', borderRadius: '3px', cursor: 'pointer', fontSize: '12px' }}>
        Connect
      </button>
      <button onClick={onDismiss} style={{ padding: '4px 8px', background: 'transparent', color: '#888', border: 'none', cursor: 'pointer', fontSize: '16px' }}>
        ×
      </button>
    </div>
  </div>
)

// ── Main Board ───────────────────────────────────────────────────────────────

export const Board: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [loading, setLoading] = useState(true)
  const [showSettings, setShowSettings] = useState(false)
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [addingCategory, setAddingCategory] = useState(false)
  const [newCategoryName, setNewCategoryName] = useState('')
  const [showBanner, setShowBanner] = useState(false)
  const [pendingMirrorCount, setPendingMirrorCount] = useState(0)
  const [confirmation, setConfirmation] = useState<ConfirmationPayload | null>(null)

  // Register the global confirmation hook called by Python via evaluate_js
  useEffect(() => {
    window.__vtbShowConfirmation = (payload: ConfirmationPayload) => {
      setConfirmation(payload)
    }
    return () => { delete window.__vtbShowConfirmation }
  }, [])

  const handleConfirmationAction = async (action: 'accept' | 'edit' | 'cancel') => {
    setConfirmation(null)
    await api.submitConfirmation(action)
    if (action !== 'cancel') loadData()
  }

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 500)
    return () => clearInterval(interval)
  }, [])

  const loadData = async () => {
    try {
      const config = await (window.pywebview?.api.get_config?.() ?? Promise.resolve(null))
      if (!config || !config.gemini_api_key) {
        setShowOnboarding(true)
        setLoading(false)
        return
      }

      const [tasksData, categoriesData, pending] = await Promise.all([
        api.getTasks(true),   // include done tasks for Done tab
        api.getCategories(),
        api.getPendingMirrorCount(),
      ])
      setTasks(tasksData || [])
      setCategories(categoriesData || [])
      setPendingMirrorCount(pending)
      setShowBanner(!config.connect_banner_dismissed && !config.remote_provider)
      setShowOnboarding(false)
    } catch (e) {
      console.error('Failed to load data', e)
    } finally {
      setLoading(false)
    }
  }

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event
    if (over && active.id !== over.id) {
      const taskId = Number(active.id)
      const categoryId = Number(over.id)
      try {
        await api.moveTask(taskId, categoryId)
        loadData()
      } catch (e) {
        console.error('Failed to move task', e)
      }
    }
  }

  const handleAddCategory = async () => {
    const name = newCategoryName.trim()
    if (!name) {
      setAddingCategory(false)
      setNewCategoryName('')
      return
    }
    try {
      await api.addCategory(name)
      setNewCategoryName('')
      setAddingCategory(false)
      loadData()
    } catch (e) {
      console.error('Failed to add category', e)
    }
  }

  const handleDismissBanner = async () => {
    setShowBanner(false)
    await api.dismissConnectBanner()
  }

  if (loading) {
    return <div style={{ padding: '20px' }}>Loading...</div>
  }

  if (showOnboarding) {
    return <Onboarding isOpen={true} onComplete={() => { setShowOnboarding(false); loadData() }} />
  }

  return (
    <DndContext onDragEnd={handleDragEnd}>
      <div style={{ padding: '16px', height: '100vh', overflow: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h1 style={{ fontSize: '24px' }}>Voice Task Board</h1>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            {pendingMirrorCount > 0 && (
              <span style={{ fontSize: '12px', color: '#90a4ae', background: '#eceff1', padding: '3px 8px', borderRadius: '8px' }}>
                ⏳ {pendingMirrorCount} pending sync
              </span>
            )}
            <button
              onClick={() => setShowSettings(true)}
              style={{ padding: '8px 16px', background: '#2196F3', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '14px' }}
            >
              Settings
            </button>
          </div>
        </div>

        {showBanner && (
          <RemoteBanner
            pendingCount={pendingMirrorCount}
            onConnect={() => setShowSettings(true)}
            onDismiss={handleDismissBanner}
          />
        )}

        <div style={{ display: 'flex', gap: '12px', minWidth: '100%' }}>
          {categories.map((category) => (
            <Column
              key={category.id}
              categoryId={category.id}
              categoryName={category.name}
              tasks={tasks}
              onTasksChange={loadData}
            />
          ))}

          {addingCategory ? (
            <div style={{ minWidth: '260px', padding: '12px', background: '#f5f5f5', borderRadius: '8px', border: '2px dashed #2196F3', height: 'fit-content' }}>
              <input
                autoFocus
                type="text"
                value={newCategoryName}
                onChange={(e) => setNewCategoryName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleAddCategory()
                  if (e.key === 'Escape') { setAddingCategory(false); setNewCategoryName('') }
                }}
                onBlur={handleAddCategory}
                placeholder="Category name"
                style={{ width: '100%', padding: '8px', border: '1px solid #ddd', borderRadius: '4px', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </div>
          ) : (
            <button
              onClick={() => setAddingCategory(true)}
              title="Add new category"
              style={{ minWidth: '80px', height: '80px', background: '#fff', border: '2px dashed #2196F3', borderRadius: '8px', color: '#2196F3', fontSize: '40px', lineHeight: 1, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, alignSelf: 'flex-start' }}
            >
              +
            </button>
          )}
        </div>

        <Settings
          isOpen={showSettings}
          onClose={() => setShowSettings(false)}
          onConfigChanged={loadData}
        />

        {confirmation && (
          <ConfirmationOverlay payload={confirmation} onAction={handleConfirmationAction} />
        )}
      </div>
    </DndContext>
  )
}
