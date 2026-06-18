import { describe, it, expect } from 'vitest'
import { taskDragId, categoryDropId, parseTaskDragId, parseCategoryDropId } from './dndIds'

describe('dnd id namespacing', () => {
  it('produces prefixed, distinct ids', () => {
    expect(taskDragId(1)).toBe('task-1')
    expect(categoryDropId(1)).toBe('category-1')
  })

  it('keeps task 1 and category 1 from colliding (the original bug)', () => {
    // Both ids were bare `1` before, so dnd-kit saw active.id === over.id and
    // silently skipped the move. Prefixing makes them unambiguous.
    expect(taskDragId(1)).not.toBe(categoryDropId(1))
  })

  it('round-trips ids back to numbers', () => {
    expect(parseTaskDragId(taskDragId(42))).toBe(42)
    expect(parseCategoryDropId(categoryDropId(7))).toBe(7)
  })

  it('rejects cross-namespace ids', () => {
    // A category id must not parse as a task id, and vice versa.
    expect(parseTaskDragId(categoryDropId(3))).toBeNull()
    expect(parseCategoryDropId(taskDragId(3))).toBeNull()
  })

  it('returns null for malformed ids', () => {
    expect(parseTaskDragId('task-')).toBeNull()
    expect(parseTaskDragId('garbage')).toBeNull()
    expect(parseCategoryDropId('category-abc')).toBeNull()
  })
})
