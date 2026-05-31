import type { Task } from '@/types/domain'

export function formatDue(task: Task): string | null {
  if (!task.due_at_utc) return null
  try {
    if (task.is_full_day) return task.due_at_utc.slice(0, 10)
    const d = new Date(task.due_at_utc.endsWith('Z') ? task.due_at_utc : task.due_at_utc + 'Z')
    if (isNaN(d.getTime())) return null
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return null }
}

export function toLocalInput(task: Task): string {
  if (!task.due_at_utc) return ''
  if (task.is_full_day) return task.due_at_utc.slice(0, 10)
  try {
    const d = new Date(task.due_at_utc.endsWith('Z') ? task.due_at_utc : task.due_at_utc + 'Z')
    if (isNaN(d.getTime())) return ''
    // shift to local time for datetime-local input
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    return local.toISOString().slice(0, 16)
  } catch { return '' }
}

export function isDueSoon(task: Task): boolean {
  if (!task.due_at_utc || task.is_full_day) return false
  try {
    const due = new Date(task.due_at_utc.endsWith('Z') ? task.due_at_utc : task.due_at_utc + 'Z')
    const diff = due.getTime() - Date.now()
    return diff > 0 && diff < task.lead_time_minutes * 60 * 1000 * 2
  } catch { return false }
}

export function isOverdue(task: Task): boolean {
  if (!task.due_at_utc) return false
  try {
    const due = new Date(task.due_at_utc.endsWith('Z') ? task.due_at_utc : task.due_at_utc + 'Z')
    return due.getTime() < Date.now()
  } catch { return false }
}
