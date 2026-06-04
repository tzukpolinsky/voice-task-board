import { describe, it, expect, beforeEach, vi } from 'vitest'
import type { Task } from '@/types/domain'
import { formatDue, toLocalInput, isDueSoon, isOverdue } from './TaskCard.helpers'

// Helper to create a minimal Task object
const createTask = (overrides?: Partial<Task>): Task => ({
  id: 1,
  title: 'Test Task',
  description: '',
  category_id: 1,
  category_name: 'Test',
  status: 'open',
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
  due_at_utc: null,
  due_tz: null,
  is_full_day: false,
  lead_time_minutes: 30,
  recurrence_rule: null,
  recurrence_until: null,
  is_recurrence: false,
  mirror_to_remote: false,
  external_provider: null,
  external_id: null,
  mirror_pending: false,
  has_drift: false,
  reminder_fired: false,
  ...overrides,
})

describe('TaskCard Helpers', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  describe('isOverdue', () => {
    it('returns false when due_at_utc is null', () => {
      const task = createTask({ due_at_utc: null })
      expect(isOverdue(task)).toBe(false)
    })

    it('returns true when due date is in the past', () => {
      vi.setSystemTime(new Date('2025-06-01T12:00:00Z'))
      const task = createTask({ due_at_utc: '2025-05-31T12:00:00Z' })
      expect(isOverdue(task)).toBe(true)
    })

    it('returns false when due date is in the future', () => {
      vi.setSystemTime(new Date('2025-06-01T12:00:00Z'))
      const task = createTask({ due_at_utc: '2025-06-02T12:00:00Z' })
      expect(isOverdue(task)).toBe(false)
    })

    it('returns false for current moment', () => {
      vi.setSystemTime(new Date('2025-06-01T12:00:00Z'))
      const task = createTask({ due_at_utc: '2025-06-01T12:00:00Z' })
      expect(isOverdue(task)).toBe(false)
    })

    it('handles malformed dates gracefully', () => {
      const task = createTask({ due_at_utc: 'invalid-date' })
      expect(isOverdue(task)).toBe(false)
    })
  })

  describe('isDueSoon', () => {
    it('returns false when due_at_utc is null', () => {
      const task = createTask({ due_at_utc: null })
      expect(isDueSoon(task)).toBe(false)
    })

    it('returns false for full-day tasks', () => {
      vi.setSystemTime(new Date('2025-06-01T12:00:00Z'))
      const task = createTask({
        due_at_utc: '2025-06-01T23:59:59Z',
        is_full_day: true,
        lead_time_minutes: 30,
      })
      expect(isDueSoon(task)).toBe(false)
    })

    it('returns true when due within lead_time_minutes * 2', () => {
      vi.setSystemTime(new Date('2025-06-01T12:00:00Z'))
      // lead_time_minutes = 30, so within 60 minutes should be soon
      const task = createTask({
        due_at_utc: '2025-06-01T12:30:00Z',
        lead_time_minutes: 30,
      })
      expect(isDueSoon(task)).toBe(true)
    })

    it('returns false when due time is outside lead_time_minutes * 2', () => {
      vi.setSystemTime(new Date('2025-06-01T12:00:00Z'))
      const task = createTask({
        due_at_utc: '2025-06-01T14:00:00Z',
        lead_time_minutes: 30,
      })
      expect(isDueSoon(task)).toBe(false)
    })

    it('returns false when already overdue', () => {
      vi.setSystemTime(new Date('2025-06-01T12:00:00Z'))
      const task = createTask({
        due_at_utc: '2025-05-31T12:00:00Z',
        lead_time_minutes: 30,
      })
      expect(isDueSoon(task)).toBe(false)
    })
  })

  describe('formatDue', () => {
    it('returns null when due_at_utc is null', () => {
      const task = createTask({ due_at_utc: null })
      expect(formatDue(task)).toBeNull()
    })

    it('returns date string (YYYY-MM-DD) for full-day tasks', () => {
      const task = createTask({
        due_at_utc: '2025-06-15T12:34:56Z',
        is_full_day: true,
      })
      expect(formatDue(task)).toBe('2025-06-15')
    })

    it('returns formatted datetime for timed tasks', () => {
      const task = createTask({
        due_at_utc: '2025-06-15T14:30:00Z',
        is_full_day: false,
      })
      const result = formatDue(task)
      expect(result).toBeTruthy()
      expect(result).toContain('Jun')
      expect(result).toContain('15')
    })

    it('handles dates without Z suffix', () => {
      const task = createTask({
        due_at_utc: '2025-06-15T14:30:00',
        is_full_day: false,
      })
      const result = formatDue(task)
      expect(result).toBeTruthy()
    })

    it('returns null for malformed dates', () => {
      const task = createTask({ due_at_utc: 'invalid-date' })
      expect(formatDue(task)).toBeNull()
    })
  })

  describe('toLocalInput', () => {
    it('returns empty string when due_at_utc is null', () => {
      const task = createTask({ due_at_utc: null })
      expect(toLocalInput(task)).toBe('')
    })

    it('returns date string (YYYY-MM-DD) for full-day tasks', () => {
      const task = createTask({
        due_at_utc: '2025-06-15T12:34:56Z',
        is_full_day: true,
      })
      expect(toLocalInput(task)).toBe('2025-06-15')
    })

    it('returns datetime-local format for timed tasks', () => {
      const task = createTask({
        due_at_utc: '2025-06-15T14:30:00Z',
        is_full_day: false,
      })
      const result = toLocalInput(task)
      // Should be in datetime-local format: YYYY-MM-DDTHH:MM
      expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
    })

    it('returns empty string for malformed dates', () => {
      const task = createTask({ due_at_utc: 'invalid-date' })
      expect(toLocalInput(task)).toBe('')
    })

    it('round-trips correctly for full-day tasks', () => {
      const task = createTask({
        due_at_utc: '2025-06-15T12:34:56Z',
        is_full_day: true,
      })
      const localInput = toLocalInput(task)
      expect(localInput).toBe('2025-06-15')
    })
  })
})
