import type {
  Category,
  Task,
  ArchivedTask,
} from './types/domain'

export type {
  Category,
  Task,
  ArchivedTask,
} from './types/domain'

export const api = {
  getTasks: async (includeDone = false): Promise<Task[]> => {
    return window.pywebview?.api.get_tasks(includeDone) ?? []
  },

  getCategories: async (): Promise<Category[]> => {
    return window.pywebview?.api.get_categories() ?? []
  },

  addCategory: async (name: string): Promise<number> => {
    return window.pywebview?.api.add_category(name) ?? 0
  },

  deleteCategory: async (id: number): Promise<void> => {
    return window.pywebview?.api.delete_category(id)
  },

  moveTask: async (taskId: number, categoryId: number): Promise<void> => {
    return window.pywebview?.api.move_task(taskId, categoryId)
  },

  deleteTask: async (taskId: number): Promise<void> => {
    return window.pywebview?.api.delete_task(taskId)
  },

  completeTask: async (taskId: number): Promise<void> => {
    return window.pywebview?.api.complete_task(taskId)
  },

  createTask: async (
    title: string,
    categoryId: number,
    description: string = '',
    dueAtUtc: string | null = null,
    dueTz: string | null = null,
    isFullDay: boolean = false,
    leadTimeMinutes: number = 30,
    recurrenceRule: string | null = null,
    mirrorToRemote: boolean = false,
  ): Promise<number> => {
    return window.pywebview?.api.create_task(title, categoryId, description, dueAtUtc, dueTz, isFullDay, leadTimeMinutes, recurrenceRule, mirrorToRemote) ?? 0
  },

  updateTask: async (taskId: number, title?: string | null, description?: string | null): Promise<boolean> => {
    return window.pywebview?.api.update_task(taskId, title, description) ?? false
  },

  updateTaskDue: async (
    taskId: number,
    dueAtUtc: string | null,
    dueTz: string | null,
    isFullDay: boolean,
    leadTimeMinutes: number,
    recurrenceRule: string | null = null,
  ): Promise<void> => {
    return window.pywebview?.api.update_task_due(taskId, dueAtUtc, dueTz, isFullDay, leadTimeMinutes, recurrenceRule)
  },

  setMirror: async (taskId: number, mirror: boolean): Promise<void> => {
    return window.pywebview?.api.set_mirror(taskId, mirror)
  },

  getPendingMirrorCount: async (): Promise<number> => {
    return window.pywebview?.api.get_pending_mirror_count() ?? 0
  },

  getArchivedTasks: async (categoryName?: string | null, limit = 100, offset = 0): Promise<ArchivedTask[]> => {
    return window.pywebview?.api.get_archived_tasks(categoryName, limit, offset) ?? []
  },

  dismissConnectBanner: async (): Promise<void> => {
    return window.pywebview?.api.dismiss_connect_banner()
  },

  connectRemoteProvider: async (provider: string): Promise<{ ok: boolean; error?: string }> => {
    return window.pywebview?.api.connect_remote_provider(provider) ?? { ok: false, error: 'Not available' }
  },

  disconnectRemoteProvider: async (): Promise<void> => {
    return window.pywebview?.api.disconnect_remote_provider()
  },

  submitConfirmation: async (action: string): Promise<void> => {
    return window.pywebview?.api.submit_confirmation(action)
  },
}

export {}

