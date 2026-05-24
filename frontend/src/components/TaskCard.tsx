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

export const TaskCard: React.FC<TaskCardProps> = ({ task, onChanged }) => {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: task.id,
  })

  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(task.title)
  const [description, setDescription] = useState(task.description ?? '')

  const style = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.5 : 1,
  }

  const handleDelete = async () => {
    try {
      await api.deleteTask(task.id)
      onChanged()
    } catch (e) {
      console.error('Failed to delete task', e)
    }
  }

  const handleSave = async () => {
    const t = title.trim()
    if (!t) {
      setEditing(false)
      setTitle(task.title)
      setDescription(task.description ?? '')
      return
    }
    try {
      await api.updateTask(task.id, t, description)
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

  return (
    <div
      ref={setNodeRef}
      style={{
        ...style,
        background: '#fff',
        border: '1px solid #ddd',
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
            style={{
              width: '100%',
              padding: '6px',
              fontSize: '14px',
              fontWeight: 500,
              border: '1px solid #2196F3',
              borderRadius: '3px',
              marginBottom: '6px',
              boxSizing: 'border-box',
            }}
          />
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onKeyDown={(e) => e.stopPropagation()}
            placeholder="Description (optional)"
            rows={2}
            style={{
              width: '100%',
              padding: '6px',
              fontSize: '12px',
              border: '1px solid #ddd',
              borderRadius: '3px',
              marginBottom: '6px',
              boxSizing: 'border-box',
              resize: 'vertical',
              fontFamily: 'inherit',
            }}
          />
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
            <p style={{ fontSize: '11px', color: '#888' }}>
              {new Date(task.created_at).toLocaleDateString()}
            </p>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }} {...stopDrag}>
            <button onClick={() => setEditing(true)} title="Edit" style={btn('#2196F3', '#fff')}>✎</button>
            <button onClick={handleDelete} title="Delete" style={btn('#ff4444', '#fff')}>×</button>
          </div>
        </div>
      )}
    </div>
  )
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
