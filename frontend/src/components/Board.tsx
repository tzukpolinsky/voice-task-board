import React, { useCallback, useEffect, useState } from 'react'
import { DndContext, DragEndEvent } from '@dnd-kit/core'
import type { ConfirmationPayload } from '@/types/domain'
import { api } from '@/api'
import { useTasks } from '@/hooks/useTasks'
import { useCategories } from '@/hooks/useCategories'
import { useConfig } from '@/hooks/useConfig'
import { usePendingMirrorCount } from '@/hooks/usePendingMirrorCount'
import { useToast } from '@/context/ToastContext'
import { Column } from './Column'
import { Settings } from './Settings'
import { Onboarding } from './Onboarding'
import { ConfirmationOverlay } from './ConfirmationOverlay'
import { RemoteBanner } from './RemoteBanner'
import { BoardHeader } from './BoardHeader'

export const Board: React.FC = () => {
  const tasksHook = useTasks()
  const categoriesHook = useCategories()
  const configHook = useConfig()
  const pendingHook = usePendingMirrorCount()
  const toast = useToast()

  const [showSettings, setShowSettings] = useState(false)
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [addingCategory, setAddingCategory] = useState(false)
  const [newCategoryName, setNewCategoryName] = useState('')
  const [showBanner, setShowBanner] = useState(false)
  const [confirmation, setConfirmation] = useState<ConfirmationPayload | null>(null)

  const loading = tasksHook.loading || categoriesHook.loading || configHook.loading || pendingHook.loading

  // Show errors from hooks
  useEffect(() => {
    if (tasksHook.error) {
      toast.show(`Failed to load tasks: ${tasksHook.error}`)
    }
  }, [tasksHook.error, toast])

  useEffect(() => {
    if (categoriesHook.error) {
      toast.show(`Failed to load categories: ${categoriesHook.error}`)
    }
  }, [categoriesHook.error, toast])

  useEffect(() => {
    if (configHook.error) {
      toast.show(`Failed to load config: ${configHook.error}`)
    }
  }, [configHook.error, toast])

  useEffect(() => {
    if (pendingHook.error) {
      toast.show(`Failed to load pending count: ${pendingHook.error}`)
    }
  }, [pendingHook.error, toast])

  // Combine all refetch calls into one
  const refetchAll = useCallback(() => {
    tasksHook.refetch()
    categoriesHook.refetch()
    configHook.refetch()
    pendingHook.refetch()
  }, [tasksHook.refetch, categoriesHook.refetch, configHook.refetch, pendingHook.refetch])

  // Determine if we should show onboarding
  useEffect(() => {
    if (!configHook.loading) {
      setShowOnboarding(!configHook.config || !configHook.config.gemini_api_key)
    }
  }, [configHook.config, configHook.loading])

  // Update banner visibility based on config
  useEffect(() => {
    if (configHook.config) {
      setShowBanner(!configHook.config.connect_banner_dismissed && !configHook.config.remote_provider)
    }
  }, [configHook.config])

  // Register the global confirmation hook called by Python via evaluate_js
  useEffect(() => {
    window.__vtbShowConfirmation = (payload: ConfirmationPayload) => {
      setConfirmation(payload)
    }
    return () => { delete window.__vtbShowConfirmation }
  }, [])

  // Register push signal handler and focus listener
  useEffect(() => {
    window.__vtbDataChanged = () => { refetchAll() }
    return () => { delete window.__vtbDataChanged }
  }, [refetchAll])

  useEffect(() => {
    const onFocus = () => refetchAll()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [])

  const handleConfirmationAction = async (action: 'accept' | 'edit' | 'cancel') => {
    setConfirmation(null)
    await api.submitConfirmation(action)
    if (action !== 'cancel') refetchAll()
  }

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event
    if (over && active.id !== over.id) {
      const taskId = Number(active.id)
      const categoryId = Number(over.id)
      try {
        await api.moveTask(taskId, categoryId)
        refetchAll()
      } catch (e) {
        console.error('Failed to move task', e)
        toast.show(e instanceof Error ? e.message : 'Failed to move task')
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
      refetchAll()
    } catch (e) {
      console.error('Failed to add category', e)
      toast.show(e instanceof Error ? e.message : 'Failed to add category')
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
    return <Onboarding isOpen={true} onComplete={() => { setShowOnboarding(false); refetchAll() }} />
  }

  return (
    <DndContext onDragEnd={handleDragEnd}>
      <div className="board" style={{ padding: '16px', height: '100vh', overflow: 'auto' }}>
        <BoardHeader pendingMirrorCount={pendingHook.count} onOpenSettings={() => setShowSettings(true)} />

        {showBanner && (
          <RemoteBanner
            pendingCount={pendingHook.count}
            onConnect={() => setShowSettings(true)}
            onDismiss={handleDismissBanner}
          />
        )}

        <div className="board-columns" style={{ display: 'flex', gap: '18px', minWidth: '100%' }}>
          {categoriesHook.categories.map((category) => (
            <Column
              key={category.id}
              categoryId={category.id}
              categoryName={category.name}
              tasks={tasksHook.tasks}
              onTasksChange={refetchAll}
            />
          ))}

          {addingCategory ? (
            <div style={{ minWidth: '260px', padding: '12px', background: 'var(--color-surface-alt)', borderRadius: '8px', border: '2px dashed var(--color-primary)', height: 'fit-content' }}>
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
                style={{ width: '100%', padding: '8px', border: '1px solid var(--color-border)', borderRadius: '4px', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </div>
          ) : (
            <button
              onClick={() => setAddingCategory(true)}
              title="Add new category"
              style={{ minWidth: '80px', height: '80px', background: 'var(--color-surface)', border: '2px dashed var(--color-primary)', borderRadius: '8px', color: 'var(--color-primary)', fontSize: '40px', lineHeight: 1, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, alignSelf: 'flex-start' }}
            >
              +
            </button>
          )}
        </div>

        <Settings
          isOpen={showSettings}
          onClose={() => setShowSettings(false)}
          onConfigChanged={refetchAll}
        />

        {confirmation && (
          <ConfirmationOverlay payload={confirmation} onAction={handleConfirmationAction} />
        )}
      </div>
    </DndContext>
  )
}
