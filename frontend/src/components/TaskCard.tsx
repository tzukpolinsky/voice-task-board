import React, { useState } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { Task, api } from '../api'

interface TaskCardProps {
  task: Task
  onChanged: () => void
}

const stopDrag = {
  onPointerDown: (e: React.PointerEvent) => e.stopPropagation(),
  onMouseDown: (e: React.MouseEvent) => e.stopPropagation(),
  onKeyDown: (e: React.KeyboardEvent) => e.stopPropagation(),
}

function formatDue(task: Task): string | null {
  if (!task.due_at_utc) return null
  try {
    if (task.is_full_day) return task.due_at_utc.slice(0, 10)
    const d = new Date(task.due_at_utc.endsWith('Z') ? task.due_at_utc : task.due_at_utc + 'Z')
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return null }
}

function toLocalInput(task: Task): string {
  if (!task.due_at_utc) return ''
  if (task.is_full_day) return task.due_at_utc.slice(0, 10)
  try {
    const d = new Date(task.due_at_utc.endsWith('Z') ? task.due_at_utc : task.due_at_utc + 'Z')
    // shift to local time for datetime-local input
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    return local.toISOString().slice(0, 16)
  } catch { return '' }
}

function isDueSoon(task: Task): boolean {
  if (!task.due_at_utc || task.is_full_day) return false
  try {
    const due = new Date(task.due_at_utc.endsWith('Z') ? task.due_at_utc : task.due_at_utc + 'Z')
    const diff = due.getTime() - Date.now()
    return diff > 0 && diff < task.lead_time_minutes * 60 * 1000 * 2
  } catch { return false }
}

function isOverdue(task: Task): boolean {
  if (!task.due_at_utc) return false
  try {
    const due = new Date(task.due_at_utc.endsWith('Z') ? task.due_at_utc : task.due_at_utc + 'Z')
    return due.getTime() < Date.now()
  } catch { return false }
}

export const TaskCard: React.FC<TaskCardProps> = ({ task, onChanged }) => {
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
    ? '#ff9800'
    : overdue
    ? '#f44336'
    : dueSoon
    ? '#ff9800'
    : '#ddd'

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
    }
  }

  const handleComplete = async () => {
    try {
      await api.completeTask(task.id)
      onChanged()
    } catch (e) {
      console.error('Failed to complete task', e)
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
    } finally {
      setTogglingMirror(false)
    }
  }

  return (
    <div
      ref={setNodeRef}
      style={{
        ...style,
        background: '#fff',
        border: `1px solid ${borderColor}`,
        borderRadius: '4px',
        padding: '12px',
        marginBottom: '8px',
        boxShadow: isDragging ? '0 4px 12px rgba(0,0,0,0.2)' : '0 1px 3px rgba(0,0,0,0.1)',
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
            <label style={{ fontSize: '12px', color: '#555', flexShrink: 0 }}>Due:</label>
            <input
              type={isFullDayEdit ? 'date' : 'datetime-local'}
              value={dueInput}
              onChange={(e) => setDueInput(e.target.value)}
              style={{ fontSize: '12px', padding: '4px 6px', border: '1px solid #ddd', borderRadius: '3px', flex: 1, minWidth: 0 }}
            />
            <label style={{ fontSize: '12px', color: '#555', display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
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
                style={{ fontSize: '11px', padding: '2px 6px', background: '#eee', border: '1px solid #ccc', borderRadius: '3px', cursor: 'pointer' }}
              >
                ✕
              </button>
            )}
          </div>

          {/* Lead time — only when due date is set */}
          {dueInput && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <label style={{ fontSize: '12px', color: '#555', flexShrink: 0 }}>Remind:</label>
              <select
                value={leadTimeEdit}
                onChange={(e) => setLeadTimeEdit(Number(e.target.value))}
                style={{ fontSize: '12px', padding: '4px 6px', border: '1px solid #ddd', borderRadius: '3px' }}
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
            <label style={{ fontSize: '12px', color: '#555', flexShrink: 0 }}>Repeat:</label>
            <input
              type="text"
              value={recurrenceEdit}
              onChange={(e) => setRecurrenceEdit(e.target.value)}
              placeholder="e.g. every day, every monday at 09:00"
              style={{ fontSize: '12px', padding: '4px 6px', border: '1px solid #ddd', borderRadius: '3px', flex: 1 }}
            />
          </div>

          <div style={{ display: 'flex', gap: '4px', justifyContent: 'flex-end' }}>
            <button onClick={handleCancel} style={btn('#ccc', '#000')}>Cancel</button>
            <button onClick={handleSave} style={btn('#2196F3', '#fff')}>Save</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: '8px' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <p style={{ fontWeight: 500, marginBottom: '4px', wordBreak: 'break-word' }}>{task.title}</p>
            {task.description && (
              <p style={{ fontSize: '12px', color: '#444', marginBottom: '4px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {task.description}
              </p>
            )}

            {/* Due date row */}
            {dueLabel && (
              <p style={{ fontSize: '11px', color: overdue ? '#f44336' : dueSoon ? '#ff9800' : '#666', marginBottom: '2px', fontWeight: overdue || dueSoon ? 600 : 400 }}>
                ⏰ {dueLabel}
                {task.recurrence_rule && <span title={task.recurrence_rule}> ↻ {task.recurrence_rule}</span>}
              </p>
            )}

            {/* Status badges */}
            <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '2px' }}>
              {task.has_drift && (
                <span title="Remote task differs from local" style={badge('#ff9800')}>⚠ remote differs</span>
              )}
              {task.mirror_pending && (
                <span title="Waiting to sync to remote" style={badge('#90a4ae')}>⏳ sync pending</span>
              )}
              {task.mirror_to_remote && !task.mirror_pending && task.external_id && (
                <span title={`Mirrored to ${task.external_provider}`} style={badge('#4caf50')}>
                  {task.external_provider === 'google' ? '☁ Google' : '☁ Remote'}
                </span>
              )}
            </div>

            <p style={{ fontSize: '11px', color: '#bbb', marginTop: '4px' }}>
              {new Date(task.created_at).toLocaleDateString()}
            </p>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flexShrink: 0 }} {...stopDrag}>
            <button onClick={openEdit} title="Edit" style={btn('#2196F3', '#fff')}>✎</button>
            <button onClick={handleComplete} title="Mark done" style={btn('#4CAF50', '#fff')}>✓</button>
            <button
              onClick={handleToggleMirror}
              disabled={togglingMirror}
              title={task.mirror_to_remote ? 'Remove from remote' : 'Mirror to remote'}
              style={btn(task.mirror_to_remote ? '#90a4ae' : '#78909c', '#fff')}
            >
              {task.mirror_to_remote ? '☁' : '⊙'}
            </button>
            <button onClick={handleDelete} title="Delete" style={btn('#ff4444', '#fff')}>×</button>
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
  border: '1px solid #2196F3',
  borderRadius: '3px',
  marginBottom: '6px',
  boxSizing: 'border-box',
}

const textareaStyle: React.CSSProperties = {
  width: '100%',
  padding: '6px',
  fontSize: '12px',
  border: '1px solid #ddd',
  borderRadius: '3px',
  marginBottom: '6px',
  boxSizing: 'border-box',
  resize: 'vertical',
  fontFamily: 'inherit',
}

const btn = (bg: string, color: string): React.CSSProperties => ({
  background: bg,
  color,
  border: 'none',
  borderRadius: '3px',
  padding: '4px 8px',
  fontSize: '12px',
  cursor: 'pointer',
  lineHeight: 1,
})

const badge = (color: string): React.CSSProperties => ({
  fontSize: '10px',
  padding: '1px 5px',
  borderRadius: '8px',
  background: color,
  color: '#fff',
  fontWeight: 500,
})
