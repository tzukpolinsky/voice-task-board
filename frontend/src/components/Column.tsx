import React, { useState } from 'react'
import { useDroppable } from '@dnd-kit/core'
import { Task, ArchivedTask, api } from '../api'
import { TaskCard } from './TaskCard'

interface ColumnProps {
  categoryId: number
  categoryName: string
  tasks: Task[]
  onTasksChange: () => void
}

export const Column: React.FC<ColumnProps> = ({ categoryId, categoryName, tasks, onTasksChange }) => {
  const openTasks = tasks.filter(t => t.category_id === categoryId && t.status !== 'done')
  const doneTasks = tasks.filter(t => t.category_id === categoryId && t.status === 'done')
  const { setNodeRef, isOver } = useDroppable({ id: categoryId })

  const [hovered, setHovered] = useState(false)
  const [adding, setAdding] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [tab, setTab] = useState<'open' | 'done'>('open')
  const [archivedTasks, setArchivedTasks] = useState<ArchivedTask[]>([])
  const [showArchived, setShowArchived] = useState(false)
  const [loadingArchived, setLoadingArchived] = useState(false)

  const handleCreate = async () => {
    const t = newTitle.trim()
    if (!t) {
      setAdding(false)
      setNewTitle('')
      return
    }
    try {
      await api.createTask(t, categoryId)
      setNewTitle('')
      setAdding(false)
      onTasksChange()
    } catch (e) {
      console.error('Failed to create task', e)
    }
  }

  const handleShowArchived = async () => {
    if (showArchived) {
      setShowArchived(false)
      return
    }
    setLoadingArchived(true)
    try {
      const items = await api.getArchivedTasks(categoryName)
      setArchivedTasks(items)
      setShowArchived(true)
    } catch (e) {
      console.error('Failed to load archived tasks', e)
    } finally {
      setLoadingArchived(false)
    }
  }

  const tabBtn = (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: '4px 8px',
    fontSize: '12px',
    fontWeight: active ? 600 : 400,
    background: active ? '#2196F3' : '#e0e0e0',
    color: active ? '#fff' : '#555',
    border: 'none',
    cursor: 'pointer',
    borderRadius: '3px',
  })

  return (
    <div
      ref={setNodeRef}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        flex: 1,
        background: isOver ? '#e3f2fd' : '#f9f9f9',
        borderRadius: '4px',
        padding: '12px',
        minHeight: '400px',
        border: isOver ? '2px solid #2196F3' : '1px solid #e0e0e0',
        transition: 'all 0.2s ease',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <h3 style={{ marginBottom: '8px', fontSize: '14px', fontWeight: 600 }}>
        {categoryName}
      </h3>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '4px', marginBottom: '10px' }}>
        <button style={tabBtn(tab === 'open')} onClick={() => setTab('open')}>
          Open ({openTasks.length})
        </button>
        <button style={tabBtn(tab === 'done')} onClick={() => setTab('done')}>
          Done ({doneTasks.length})
        </button>
      </div>

      {tab === 'open' ? (
        <>
          <div>
            {openTasks.map(task => (
              <TaskCard key={task.id} task={task} onChanged={onTasksChange} />
            ))}
          </div>

          {adding ? (
            <div style={{
              background: '#fff',
              border: '2px solid #2196F3',
              borderRadius: '4px',
              padding: '8px',
              marginTop: '4px',
            }}>
              <input
                autoFocus
                type="text"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreate()
                  if (e.key === 'Escape') { setAdding(false); setNewTitle('') }
                }}
                onBlur={handleCreate}
                placeholder="New task..."
                style={{
                  width: '100%',
                  padding: '6px',
                  border: 'none',
                  outline: 'none',
                  fontSize: '14px',
                  boxSizing: 'border-box',
                }}
              />
            </div>
          ) : (
            <button
              onClick={() => setAdding(true)}
              title="Add task"
              style={{
                marginTop: 'auto',
                paddingTop: '20px',
                paddingBottom: '20px',
                background: 'transparent',
                border: '2px dashed #ccc',
                borderRadius: '4px',
                color: '#888',
                fontSize: '24px',
                cursor: 'pointer',
                opacity: hovered ? 1 : 0,
                transition: 'opacity 0.15s ease',
                flex: 1,
                minHeight: '60px',
                lineHeight: 1,
              }}
            >
              +
            </button>
          )}
        </>
      ) : (
        /* Done tab */
        <div>
          {doneTasks.length === 0 && archivedTasks.length === 0 && (
            <p style={{ fontSize: '12px', color: '#aaa', textAlign: 'center', padding: '20px 0' }}>
              No completed tasks
            </p>
          )}
          {doneTasks.map(task => (
            <DoneCard key={task.id} task={task} onChanged={onTasksChange} />
          ))}

          {/* Show archived */}
          <button
            onClick={handleShowArchived}
            disabled={loadingArchived}
            style={{
              width: '100%',
              marginTop: '8px',
              padding: '6px',
              fontSize: '11px',
              color: '#888',
              background: 'transparent',
              border: '1px dashed #ccc',
              borderRadius: '3px',
              cursor: 'pointer',
            }}
          >
            {loadingArchived ? 'Loading...' : showArchived ? 'Hide older (30d+)' : 'Show older (30d+)'}
          </button>

          {showArchived && archivedTasks.map(task => (
            <ArchivedCard key={task.id} task={task} />
          ))}
        </div>
      )}
    </div>
  )
}

const DoneCard: React.FC<{ task: Task; onChanged: () => void }> = ({ task }) => {
  return (
    <div style={{
      background: '#f0f0f0',
      border: '1px solid #ddd',
      borderRadius: '4px',
      padding: '10px 12px',
      marginBottom: '6px',
      opacity: 0.8,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: '8px' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{ fontWeight: 500, fontSize: '13px', textDecoration: 'line-through', color: '#666', marginBottom: '2px', wordBreak: 'break-word' }}>
            {task.title}
          </p>
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '11px', color: '#aaa' }}>
              {new Date(task.updated_at).toLocaleDateString()}
            </span>
            {task.mirror_to_remote && (
              <span title={`Was mirrored to ${task.external_provider ?? 'remote'}`} style={{ fontSize: '11px', color: '#90a4ae' }}>
                📋 {task.external_provider === 'google' ? 'Google' : task.external_provider === 'microsoft' ? 'Microsoft' : 'Remote'}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

const ArchivedCard: React.FC<{ task: ArchivedTask }> = ({ task }) => (
  <div style={{
    background: '#fafafa',
    border: '1px dashed #e0e0e0',
    borderRadius: '4px',
    padding: '8px 12px',
    marginBottom: '4px',
    opacity: 0.6,
  }}>
    <p style={{ fontWeight: 500, fontSize: '12px', color: '#888', textDecoration: 'line-through', marginBottom: '2px', wordBreak: 'break-word' }}>
      {task.title}
    </p>
    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
      <span style={{ fontSize: '10px', color: '#bbb' }}>
        archived {new Date(task.archived_at).toLocaleDateString()}
      </span>
      {task.mirror_to_remote === 1 && (
        <span style={{ fontSize: '10px', color: '#b0bec5' }}>
          📋 {task.external_provider ?? 'remote'}
        </span>
      )}
    </div>
  </div>
)
