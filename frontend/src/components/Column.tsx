import React, { useState } from 'react'
import { useDroppable } from '@dnd-kit/core'
import { Clipboard } from 'lucide-react'
import type { Task, ArchivedTask } from '@/types/domain'
import { api } from '@/api'
import { useToast } from '@/context/ToastContext'
import { TaskCard } from './TaskCard'
import { RecurringDoneCard } from './RecurringDoneCard'
import { TaskEditModal } from './TaskEditModal'

interface ColumnProps {
  categoryId: number
  categoryName: string
  tasks: Task[]
  onTasksChange: () => void
}

export const Column: React.FC<ColumnProps> = ({ categoryId, categoryName, tasks, onTasksChange }) => {
  const toast = useToast()
  const openTasks = tasks.filter(t => t.category_id === categoryId && t.status !== 'done')
  const doneTasks = tasks.filter(t => t.category_id === categoryId && t.status === 'done')
  const { setNodeRef, isOver } = useDroppable({ id: categoryId })

  const [hovered, setHovered] = useState(false)
  const [adding, setAdding] = useState(false)
  const [tab, setTab] = useState<'open' | 'done'>('open')
  const [archivedTasks, setArchivedTasks] = useState<ArchivedTask[]>([])
  const [showArchived, setShowArchived] = useState(false)
  const [loadingArchived, setLoadingArchived] = useState(false)

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
      toast.show(e instanceof Error ? e.message : 'Failed to load archived tasks')
    } finally {
      setLoadingArchived(false)
    }
  }

  const tabBtn = (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: 'var(--space-1) var(--space-2)',
    fontSize: 'var(--text-sm)',
    fontWeight: active ? 600 : 400,
    background: active ? 'var(--color-accent)' : 'var(--color-border)',
    color: active ? 'var(--color-surface)' : 'var(--color-text-secondary)',
    border: 'none',
    cursor: 'pointer',
    borderRadius: 'var(--radius-sm)',
  })

  return (
    <div
      className="column"
      ref={setNodeRef}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        flex: 1,
        background: isOver ? 'var(--color-accent-bg)' : 'var(--color-surface-muted)',
        borderRadius: 'var(--radius-md)',
        padding: 'var(--space-3)',
        minHeight: '400px',
        border: isOver ? '2px solid var(--color-accent)' : '1px solid var(--color-border)',
        transition: 'all 0.2s ease',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div className="column-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-2)' }}>
        <h3 style={{ marginBottom: 0, fontSize: 'var(--text-md)', fontWeight: 600 }}>
          {categoryName}
        </h3>
        <span className="column-count">
          {tab === 'open' ? openTasks.length : doneTasks.length}
        </span>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 'var(--space-1)', marginBottom: 'var(--space-2)' }}>
        <button style={tabBtn(tab === 'open')} onClick={() => setTab('open')}>
          Open ({openTasks.length})
        </button>
        <button style={tabBtn(tab === 'done')} onClick={() => setTab('done')}>
          Done ({doneTasks.length})
        </button>
      </div>

      {tab === 'open' ? (
        <>
          <div className="task-list">
            {openTasks.map(task => (
              <TaskCard key={task.id} task={task} onChanged={onTasksChange} />
            ))}
          </div>

          <button
            onClick={() => setAdding(true)}
            title="Add task"
            style={{
              marginTop: 'auto',
              paddingTop: 'var(--space-5)',
              paddingBottom: 'var(--space-5)',
              background: 'transparent',
              border: '2px dashed var(--color-border-strong)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--color-text-secondary)',
              fontSize: 'var(--text-xl)',
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
          {adding && (
            <TaskEditModal
              categoryId={categoryId}
              onClose={() => setAdding(false)}
              onSaved={onTasksChange}
            />
          )}
        </>
      ) : (
        /* Done tab */
        <div>
          {doneTasks.length === 0 && archivedTasks.length === 0 && (
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-faint)', textAlign: 'center', padding: 'var(--space-5) 0' }}>
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
              marginTop: 'var(--space-2)',
              padding: 'var(--space-1)',
              fontSize: 'var(--text-xs)',
              color: 'var(--color-text-secondary)',
              background: 'transparent',
              border: '1px dashed var(--color-border-strong)',
              borderRadius: 'var(--radius-sm)',
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
    <div>
      <div style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-md)',
        padding: 'var(--space-2) var(--space-3)',
        marginBottom: 'var(--space-1)',
        opacity: 0.8,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: 'var(--space-2)' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <p style={{ fontWeight: 500, fontSize: 'var(--text-base)', textDecoration: 'line-through', color: 'var(--color-text-muted)', marginBottom: 'var(--space-1)', wordBreak: 'break-word' }}>
              {task.title}
            </p>
            <div style={{ display: 'flex', gap: 'var(--space-1)', alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-faint)' }}>
                {new Date(task.updated_at).toLocaleDateString()}
              </span>
              {task.mirror_to_remote && (
                <span title={`Was mirrored to ${task.external_provider ?? 'remote'}`} style={{ fontSize: 'var(--text-xs)', color: 'var(--color-neutral)', display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <Clipboard size={10} /> {task.external_provider === 'google' ? 'Google' : task.external_provider === 'microsoft' ? 'Microsoft' : 'Remote'}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
      
      {/* Show recurring done history if this is a recurring task */}
      {task.recurrence_rule && (
        <div style={{ marginBottom: 'var(--space-1)' }}>
          <RecurringDoneCard task={task} />
        </div>
      )}
    </div>
  )
}

const ArchivedCard: React.FC<{ task: ArchivedTask }> = ({ task }) => (
  <div style={{
    background: 'var(--color-surface-alt)',
    border: '1px dashed var(--color-border)',
    borderRadius: 'var(--radius-md)',
    padding: 'var(--space-2) var(--space-3)',
    marginBottom: 'var(--space-1)',
    opacity: 0.6,
  }}>
    <p style={{ fontWeight: 500, fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)', textDecoration: 'line-through', marginBottom: 'var(--space-1)', wordBreak: 'break-word' }}>
      {task.title}
    </p>
    <div style={{ display: 'flex', gap: 'var(--space-1)', flexWrap: 'wrap' }}>
      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
        archived {new Date(task.archived_at).toLocaleDateString()}
      </span>
      {task.mirror_to_remote === 1 && (
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)', display: 'flex', alignItems: 'center', gap: '3px' }}>
          <Clipboard size={10} /> {task.external_provider ?? 'remote'}
        </span>
      )}
    </div>
  </div>
)
