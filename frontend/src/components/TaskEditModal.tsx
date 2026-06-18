import React, { useState } from 'react'
import { X } from 'lucide-react'
import DatePicker from 'react-datepicker'
import type { Task } from '@/types/domain'
import { api } from '@/api'
import { useToast } from '@/context/ToastContext'
import { toLocalDate } from './TaskCard.helpers'
import { RecurrenceSelect } from './RecurrenceSelect'
import 'react-datepicker/dist/react-datepicker.css'
import '../styles/TaskEditModal.css'

interface TaskEditModalProps {
  /** Present → edit that task. Absent → create a new task in `categoryId`. */
  task?: Task
  /** Required in create mode: the column the "+" was pressed in. */
  categoryId?: number
  onClose: () => void
  onSaved: () => void
}

export const TaskEditModal: React.FC<TaskEditModalProps> = ({ task, categoryId, onClose, onSaved }) => {
  const toast = useToast()
  const isEdit = !!task

  const [title, setTitle] = useState(task?.title ?? '')
  const [description, setDescription] = useState(task?.description ?? '')
  const [dueDate, setDueDate] = useState<Date | null>(task ? toLocalDate(task) : null)
  const [isFullDay, setIsFullDay] = useState(task?.is_full_day ?? false)
  const [leadTime, setLeadTime] = useState(task?.lead_time_minutes ?? 30)
  const [recurrence, setRecurrence] = useState<string | null>(task?.recurrence_rule ?? null)
  const [until, setUntil] = useState<string | null>(
    task?.recurrence_until ? task.recurrence_until.slice(0, 10) : null,
  )
  const [saving, setSaving] = useState(false)

  const heading = isEdit ? `Edit task — ${task!.title}` : 'New task'

  const handleSave = async () => {
    const t = title.trim()
    if (!t) {
      toast.show('Title is required')
      return
    }
    setSaving(true)
    try {
      let dueAtUtc: string | null = null
      let dueTz: string | null = null
      if (dueDate) {
        if (isFullDay) {
          // Store the local calendar day as a bare date — no instant, no tz shift.
          const y = dueDate.getFullYear()
          const m = String(dueDate.getMonth() + 1).padStart(2, '0')
          const d = String(dueDate.getDate()).padStart(2, '0')
          dueAtUtc = `${y}-${m}-${d}T00:00:00`
        } else {
          dueAtUtc = dueDate.toISOString().slice(0, 19)
        }
        dueTz = Intl.DateTimeFormat().resolvedOptions().timeZone
      }

      let taskId: number
      if (isEdit) {
        await api.updateTask(task!.id, t, description)
        taskId = task!.id
      } else {
        // Category carried silently from the column the "+" was pressed in.
        taskId = await api.createTask(t, categoryId!, description)
      }

      // Due/lead/full-day. Recurrence handled by setRecurrence() so the AI
      // text→RRULE conversion, the UNTIL date, and (re)materialization all
      // happen in one place.
      await api.updateTaskDue(taskId, dueAtUtc, dueTz, isFullDay, leadTime, null)
      await api.setRecurrence(taskId, recurrence, until)

      onSaved()
      onClose()
    } catch (e) {
      console.error('Failed to save task', e)
      toast.show(e instanceof Error ? e.message : 'Failed to save task')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="task-modal" onClick={(e) => e.stopPropagation()}>
        <div className="task-modal-header">
          <h2 className="task-modal-title">{heading}</h2>
          <button className="task-modal-close" onClick={onClose} title="Close" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <input
          autoFocus
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) handleSave()
            if (e.key === 'Escape') onClose()
          }}
          placeholder="Task title"
          className="task-edit-input task-edit-input--title"
        />

        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description (optional)"
          rows={4}
          className="task-edit-input task-edit-input--area"
        />

        {/* Due + All day on one row */}
        <div className="task-modal-row">
          <label className="task-edit-label">Due</label>
          <DatePicker
            selected={dueDate}
            onChange={(d) => setDueDate(d)}
            showTimeSelect={!isFullDay}
            timeIntervals={15}
            dateFormat={isFullDay ? 'EEE, MMM d, yyyy' : 'EEE, MMM d, yyyy h:mm aa'}
            placeholderText={isFullDay ? 'Pick a date' : 'Pick a date & time'}
            className="task-edit-input task-edit-input--inline"
            popperClassName="vtb-datepicker-popper"
            wrapperClassName="vtb-datepicker-wrapper"
            shouldCloseOnSelect={isFullDay}
            isClearable
          />
          <label className="task-edit-check">
            <input
              type="checkbox"
              checked={isFullDay}
              onChange={(e) => setIsFullDay(e.target.checked)}
            />
            All day
          </label>
        </div>

        {/* Remind — only when a timed due date is set */}
        {dueDate && !isFullDay && (
          <div className="task-modal-row">
            <label className="task-edit-label">Remind</label>
            <select
              value={leadTime}
              onChange={(e) => setLeadTime(Number(e.target.value))}
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

        {/* Repeats (+ Until inside RecurrenceSelect) */}
        <div className="task-modal-row task-modal-row--repeats">
          <RecurrenceSelect
            value={recurrence}
            until={until}
            onChange={(repeat, u) => {
              setRecurrence(repeat)
              setUntil(u)
            }}
          />
        </div>

        <div className="task-modal-actions">
          <button onClick={onClose} className="btn-secondary" disabled={saving}>Cancel</button>
          <button onClick={handleSave} className="btn-primary" disabled={saving}>
            {saving ? 'Saving…' : isEdit ? 'Save' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}
