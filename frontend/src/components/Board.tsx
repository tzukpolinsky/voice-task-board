import React, { useEffect, useState } from 'react'
import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { Task, Category, api } from '../api'
import { Column } from './Column'
import { Settings } from './Settings'
import { Onboarding } from './Onboarding'

export const Board: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [loading, setLoading] = useState(true)
  const [showSettings, setShowSettings] = useState(false)
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [addingCategory, setAddingCategory] = useState(false)
  const [newCategoryName, setNewCategoryName] = useState('')

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

      const [tasksData, categoriesData] = await Promise.all([
        api.getTasks(),
        api.getCategories(),
      ])
      setTasks(tasksData || [])
      setCategories(categoriesData || [])
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

  if (loading) {
    return <div style={{ padding: '20px' }}>Loading...</div>
  }

  if (showOnboarding) {
    return <Onboarding isOpen={true} onComplete={() => { setShowOnboarding(false); loadData() }} />
  }

  return (
    <DndContext onDragEnd={handleDragEnd}>
      <div style={{
        padding: '16px',
        height: '100vh',
        overflow: 'auto',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h1 style={{ fontSize: '24px' }}>Voice Task Board</h1>
          <button
            onClick={() => setShowSettings(true)}
            style={{
              padding: '8px 16px',
              background: '#2196F3',
              color: '#fff',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '14px',
            }}
          >
            Settings
          </button>
        </div>

        <div style={{
          display: 'flex',
          gap: '12px',
          minWidth: '100%',
        }}>
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
            <div style={{
              minWidth: '260px',
              padding: '12px',
              background: '#f5f5f5',
              borderRadius: '8px',
              border: '2px dashed #2196F3',
              height: 'fit-content',
            }}>
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
                style={{
                  width: '100%',
                  padding: '8px',
                  border: '1px solid #ddd',
                  borderRadius: '4px',
                  fontSize: '14px',
                  boxSizing: 'border-box',
                }}
              />
            </div>
          ) : (
            <button
              onClick={() => setAddingCategory(true)}
              title="Add new category"
              style={{
                minWidth: '80px',
                height: '80px',
                background: '#fff',
                border: '2px dashed #2196F3',
                borderRadius: '8px',
                color: '#2196F3',
                fontSize: '40px',
                lineHeight: 1,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                alignSelf: 'flex-start',
              }}
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
      </div>
    </DndContext>
  )
}
