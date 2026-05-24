import React, { useState } from 'react'
import { useDroppable } from '@dnd-kit/core'
import { Task, api } from '../api'
import { TaskCard } from './TaskCard'

interface ColumnProps {
  categoryId: number
  categoryName: string
  tasks: Task[]
  onTasksChange: () => void
}

export const Column: React.FC<ColumnProps> = ({ categoryId, categoryName, tasks, onTasksChange }) => {
  const categoryTasks = tasks.filter(t => t.category_id === categoryId)
  const { setNodeRef, isOver } = useDroppable({ id: categoryId })

  const [hovered, setHovered] = useState(false)
  const [adding, setAdding] = useState(false)
  const [newTitle, setNewTitle] = useState('')

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
      <h3 style={{ marginBottom: '12px', fontSize: '14px', fontWeight: 600 }}>
        {categoryName} ({categoryTasks.length})
      </h3>
      <div>
        {categoryTasks.map(task => (
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
    </div>
  )
}
