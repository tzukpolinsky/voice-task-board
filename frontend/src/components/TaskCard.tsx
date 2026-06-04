import React, { useState } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { Pencil, Check, Cloud, CloudOff, Trash2, X, Clock, Repeat, AlertTriangle, Loader } from 'lucide-react'
import type { Task } from '@/types/domain'
import { api } from '@/api'
import { useToast } from '@/context/ToastContext'
import { formatDue, toLocalInput, isDueSoon, isOverdue } from './TaskCard.helpers'
import { RecurrenceSelect } from './RecurrenceSelect'
import { RecurringCompleteButton } from './RecurringCompleteButton'

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
  const [recurrenceEdit, setRecurrenceEdit] = useState<string | null>(null)
  const [untilEdit, setUntilEdit] = useState<string | null>(null)
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
    setRecurrenceEdit(task.recurrence_rule ?? null)
    setUntilEdit(null) // TODO: read from task once stored
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
        recurrenceEdit,
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
        <div className="task-edit" {...stopDrag}>
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
            className="task-edit-input task-edit-input--title"
          />
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onKeyDown={(e) => e.stopPropagation()}
            placeholder="Description (optional)"
            rows={4}
            className="task-edit-input task-edit-input--area"
          />

          {/* Due date row */}
          <div className="task-edit-row">
            <label className="task-edit-label">Due:</label>
            <input
              type={isFullDayEdit ? 'date' : 'datetime-local'}
              value={dueInput}
              onChange={(e) => setDueInput(e.target.value)}
              className="task-edit-input task-edit-input--inline"
            />
            <label className="task-edit-check">
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
                className="task-edit-clear"
              >
                <X size={12} />
              </button>
            )}
          </div>

          {/* Lead time — only when due date is set */}
          {dueInput && (
            <div className="task-edit-row">
              <label className="task-edit-label">Remind:</label>
              <select
                value={leadTimeEdit}
                onChange={(e) => setLeadTimeEdit(Number(e.target.value))}
                className="task-edit-input task-edit-input--inline"
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
          <div className="task-edit-row" {...stopDrag}>
            <RecurrenceSelect
              value={recurrenceEdit}
              until={untilEdit}
              onChange={(repeat, until) => {
                setRecurrenceEdit(repeat)
                setUntilEdit(until)
              }}
            />
          </div>

          <div className="task-edit-actions">
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
              </p>
            )}

            {/* Recurrence info */}
            {task.recurrence_rule && (
              <p style={{ fontSize: '10px', color: 'var(--color-text-faint)', marginBottom: '4px', fontStyle: 'italic' }}>
                <span style={{ marginRight: '8px' }}>
                  <Repeat size={11} style={{ display: 'inline', marginRight: '2px', verticalAlign: '-1px' }} /> 
                  Repeating for up to 1 year
                </span>
              </p>
            )}

            {/* Status badges */}
            <div className="task-card-tags" style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '2px' }}>
              {task.recurrence_rule && (
                <span className="task-card-tag task-card-tag--info" title={`Repeats: ${task.recurrence_rule}`} style={{ fontSize: '10px', padding: '2px 6px' }}>
                  <Repeat size={11} style={{ display: 'inline', marginRight: '2px' }} /> Repeating
                </span>
              )}
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
            {task.recurrence_rule ? (
              <RecurringCompleteButton task={task} onChanged={onChanged} />
            ) : (
              <button className="task-card-action task-card-action--success" onClick={handleComplete} title="Mark done"><Check size={14} /></button>
            )}
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
