import React, { useState } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { Pencil, Check, Cloud, CloudOff, Trash2, X, Clock, Repeat, AlertTriangle, Loader } from 'lucide-react'
import type { Task } from '@/types/domain'
import { api } from '@/api'
import { useToast } from '@/context/ToastContext'
import { formatDue, toLocalInput, isDueSoon, isOverdue } from './TaskCard.helpers'

interface TaskCardProps {
  task: Task
  onChanged: () => void
}

const stopDrag = {
  onPointerDown: (e: React.PointerEvent) => e.stopPropagation(),
  onMouseDown: (e: React.MouseEvent) => e.stopPropagation(),
  onKeyDown: (e: React.KeyboardEvent) => e.stopPropagation(),
}

export const TaskCard: React.FC<TaskCardProps> = ({ task, onChanged }) => {
  const toast = useToast()
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: task.id,
  })

  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(task.title)
  const [description, setDescription] = useState(task.description ?? '')
  const [dueInput, setDueInput] = useState('')
  const [isFullDayEdit, setIsFullDayEdit] = useState(false)
  const [leadTimeEdit, setLeadTimeEdit] = useState(30)
  const [recurrenceEdit, setRecurrenceEdit] = useState('')
  const [togglingMirror, setTogglingMirror] = useState(false)

  const style = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.5 : 1,
  }

  const overdue = isOverdue(task)
  const dueSoon = isDueSoon(task)
  const dueLabel = formatDue(task)

  const borderColor = task.has_drift
    ? 'var(--color-warning)'
    : overdue
    ? 'var(--color-danger)'
    : dueSoon
    ? 'var(--color-warning)'
    : 'var(--color-border-strong)'

  const openEdit = () => {
    setTitle(task.title)
    setDescription(task.description ?? '')
    setDueInput(toLocalInput(task))
    setIsFullDayEdit(task.is_full_day)
    setLeadTimeEdit(task.lead_time_minutes)
    setRecurrenceEdit(task.recurrence_rule ?? '')
    setEditing(true)
  }

  const handleDelete = async () => {
    try {
      await api.deleteTask(task.id)
      onChanged()
    } catch (e) {
      console.error('Failed to delete task', e)
      toast.show(e instanceof Error ? e.message : 'Failed to delete task')
    }
  }

  const handleComplete = async () => {
    try {
      await api.completeTask(task.id)
      onChanged()
    } catch (e) {
      console.error('Failed to complete task', e)
      toast.show(e instanceof Error ? e.message : 'Failed to complete task')
    }
  }

  const handleSave = async () => {
    const t = title.trim()
    if (!t) {
      handleCancel()
      return
    }
    try {
      await api.updateTask(task.id, t, description)

      let dueAtUtc: string | null = null
      let dueTz: string | null = null
      if (dueInput) {
        const d = new Date(dueInput) // browser parses datetime-local as local time
        dueAtUtc = d.toISOString().slice(0, 19)
        dueTz = Intl.DateTimeFormat().resolvedOptions().timeZone
      }
      await api.updateTaskDue(
        task.id,
        dueAtUtc,
        dueTz,
        isFullDayEdit,
        leadTimeEdit,
        recurrenceEdit.trim() || null,
      )

      setEditing(false)
      onChanged()
    } catch (e) {
      console.error('Failed to update task', e)
      toast.show(e instanceof Error ? e.message : 'Failed to update task')
    }
  }

  const handleCancel = () => {
    setTitle(task.title)
    setDescription(task.description ?? '')
    setEditing(false)
  }

  const handleToggleMirror = async () => {
    setTogglingMirror(true)
    try {
      await api.setMirror(task.id, !task.mirror_to_remote)
      onChanged()
    } catch (e) {
      console.error('Failed to toggle mirror', e)
      toast.show(e instanceof Error ? e.message : 'Failed to toggle mirror')
    } finally {
      setTogglingMirror(false)
    }
  }

  const stateClass = task.has_drift || overdue ? 'priority-high' : dueSoon ? 'priority-due' : ''

  return (
    <div
      className={`task-card ${stateClass}`}
      ref={setNodeRef}
      style={{
        ...style,
        background: 'var(--color-surface)',
        border: `1px solid ${borderColor}`,
        borderRadius: 'var(--radius-md)',
        padding: 'var(--space-3)',
        marginBottom: 'var(--space-2)',
        boxShadow: isDragging ? 'var(--shadow-card-drag)' : 'var(--shadow-card)',
        cursor: editing ? 'default' : 'grab',
      }}
      {...(editing ? {} : attributes)}
      {...(editing ? {} : listeners)}
    >
      {editing ? (
        <div {...stopDrag}>
          <input
            autoFocus
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              e.stopPropagation()
              if (e.key === 'Enter' && !e.shiftKey) handleSave()
              if (e.key === 'Escape') handleCancel()
            }}
            style={inputStyle}
          />
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onKeyDown={(e) => e.stopPropagation()}
            placeholder="Description (optional)"
            rows={2}
            style={textareaStyle}
          />

          {/* Due date row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', flexWrap: 'wrap' }}>
            <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)', flexShrink: 0 }}>Due:</label>
            <input
              type={isFullDayEdit ? 'date' : 'datetime-local'}
              value={dueInput}
              onChange={(e) => setDueInput(e.target.value)}
              style={{ fontSize: '12px', padding: '4px 6px', border: '1px solid var(--color-border-strong)', borderRadius: '3px', flex: 1, minWidth: 0 }}
            />
            <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
              <input
                type="checkbox"
                checked={isFullDayEdit}
                onChange={(e) => {
                  setIsFullDayEdit(e.target.checked)
                  // keep date portion when toggling
                  if (dueInput.length >= 10) setDueInput(dueInput.slice(0, 10))
                }}
              />
              All day
            </label>
            {dueInput && (
              <button
                onClick={() => setDueInput('')}
                title="Clear due date"
                style={{ fontSize: '11px', padding: '2px 6px', background: 'var(--color-surface-alt)', border: '1px solid var(--color-border-strong)', borderRadius: '3px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}
              >
                <X size={12} />
              </button>
            )}
          </div>

          {/* Lead time — only when due date is set */}
          {dueInput && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)', flexShrink: 0 }}>Remind:</label>
              <select
                value={leadTimeEdit}
                onChange={(e) => setLeadTimeEdit(Number(e.target.value))}
                style={{ fontSize: '12px', padding: '4px 6px', border: '1px solid var(--color-border-strong)', borderRadius: '3px' }}
              >
                <option value={10}>10 min before</option>
                <option value={15}>15 min before</option>
                <option value={30}>30 min before</option>
                <option value={60}>1 hour before</option>
                <option value={120}>2 hours before</option>
                <option value={1440}>1 day before</option>
              </select>
            </div>
          )}

          {/* Recurrence */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
            <label style={{ fontSize: '12px', color: 'var(--color-text-muted)', flexShrink: 0 }}>Repeat:</label>
            <input
              type="text"
              value={recurrenceEdit}
              onChange={(e) => setRecurrenceEdit(e.target.value)}
              placeholder="e.g. every day, every monday at 09:00"
              style={{ fontSize: '12px', padding: '4px 6px', border: '1px solid var(--color-border-strong)', borderRadius: '3px', flex: 1 }}
            />
          </div>

          <div style={{ display: 'flex', gap: '4px', justifyContent: 'flex-end' }}>
            <button onClick={handleCancel} className="btn-secondary">Cancel</button>
            <button onClick={handleSave} className="btn-primary">Save</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: '8px' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <p className="task-card-title">{task.title}</p>
            {task.description && (
              <p className="task-card-description">
                {task.description}
              </p>
            )}

            {/* Due date row */}
            {dueLabel && (
              <p className="task-card-due" style={{ fontSize: '11px', color: overdue ? 'var(--color-danger)' : dueSoon ? 'var(--color-warning)' : 'var(--color-text-muted)', marginBottom: '2px', fontWeight: overdue || dueSoon ? 600 : 400, display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Clock size={12} /> {dueLabel}
                {task.recurrence_rule && <span title={task.recurrence_rule} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Repeat size={12} /> {task.recurrence_rule}</span>}
              </p>
            )}

            {/* Status badges */}
            <div className="task-card-tags" style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '2px' }}>
              {task.has_drift && (
                <span className="task-card-tag task-card-tag--warning" title="Remote task differs from local"><AlertTriangle size={12} /> remote differs</span>
              )}
              {task.mirror_pending && (
                <span className="task-card-tag task-card-tag--neutral" title="Waiting to sync to remote"><Loader size={12} /> sync pending</span>
              )}
              {task.mirror_to_remote && !task.mirror_pending && task.external_id && (
                <span className="task-card-tag task-card-tag--success" title={`Mirrored to ${task.external_provider}`}>
                  <Cloud size={12} /> {task.external_provider === 'google' ? 'Google' : 'Remote'}
                </span>
              )}
            </div>

            <p style={{ fontSize: '11px', color: 'var(--color-text-faint)', marginTop: '4px' }}>
              {new Date(task.created_at).toLocaleDateString()}
            </p>
          </div>

          <div className="task-card-actions" style={{ display: 'flex', flexDirection: 'column', gap: '4px', flexShrink: 0 }} {...stopDrag}>
            <button className="task-card-action task-card-action--primary" onClick={openEdit} title="Edit"><Pencil size={14} /></button>
            <button className="task-card-action task-card-action--success" onClick={handleComplete} title="Mark done"><Check size={14} /></button>
            <button
              className="task-card-action task-card-action--mirror"
              onClick={handleToggleMirror}
              disabled={togglingMirror}
              title={task.mirror_to_remote ? 'Remove from remote' : 'Mirror to remote'}
            >
              {task.mirror_to_remote ? <Cloud size={14} /> : <CloudOff size={14} />}
            </button>
            <button className="task-card-action task-card-action--danger" onClick={handleDelete} title="Delete"><Trash2 size={14} /></button>
          </div>
        </div>
      )}
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '6px',
  fontSize: '14px',
  fontWeight: 500,
  border: '1px solid var(--color-accent)',
  borderRadius: '3px',
  marginBottom: '6px',
  boxSizing: 'border-box',
}

const textareaStyle: React.CSSProperties = {
  width: '100%',
  padding: '6px',
  fontSize: '12px',
  border: '1px solid var(--color-border-strong)',
  borderRadius: '3px',
  marginBottom: '6px',
  boxSizing: 'border-box',
  resize: 'vertical',
  fontFamily: 'inherit',
}


