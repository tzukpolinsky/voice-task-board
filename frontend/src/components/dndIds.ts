import type { UniqueIdentifier } from '@dnd-kit/core'

// dnd-kit treats draggable and droppable identifiers as a single namespace and
// does not coerce types. Task ids and category ids are both small integers from
// separate tables, so an un-prefixed number can collide (task 1 vs category 1).
// Prefixing keeps the two namespaces distinct and self-describing.

export const taskDragId = (taskId: number): string => `task-${taskId}`
export const categoryDropId = (categoryId: number): string => `category-${categoryId}`

/** Parse a `task-<n>` draggable id back to its numeric id, or null if malformed. */
export const parseTaskDragId = (id: UniqueIdentifier): number | null => {
  const m = /^task-(\d+)$/.exec(String(id))
  return m ? Number(m[1]) : null
}

/** Parse a `category-<n>` droppable id back to its numeric id, or null if malformed. */
export const parseCategoryDropId = (id: UniqueIdentifier): number | null => {
  const m = /^category-(\d+)$/.exec(String(id))
  return m ? Number(m[1]) : null
}
