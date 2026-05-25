declare global {
  interface Window {
    pywebview?: {
      api: {
        get_tasks: (include_done?: boolean) => Promise<Task[]>
        get_categories: () => Promise<Category[]>
        add_category: (name: string) => Promise<number>
        delete_category: (id: number) => Promise<void>
        move_task: (task_id: number, category_id: number) => Promise<void>
        delete_task: (task_id: number) => Promise<void>
        complete_task: (task_id: number) => Promise<void>
        create_task: (title: string, category_id: number, description?: string, due_at_utc?: string | null, due_tz?: string | null, is_full_day?: boolean, lead_time_minutes?: number, recurrence_rule?: string | null, mirror_to_remote?: boolean) => Promise<number>
        update_task: (task_id: number, title?: string | null, description?: string | null) => Promise<boolean>
        update_task_due: (task_id: number, due_at_utc: string | null, due_tz: string | null, is_full_day: boolean, lead_time_minutes: number, recurrence_rule?: string | null) => Promise<void>
        set_mirror: (task_id: number, mirror: boolean) => Promise<void>
        get_pending_mirror_count: () => Promise<number>
        get_archived_tasks: (category_name?: string | null, limit?: number, offset?: number) => Promise<ArchivedTask[]>
        get_config: () => Promise<{ gemini_api_key: string | null; hotkey: string; remote_provider: string | null; connect_banner_dismissed: boolean }>
        save_config: (api_key: string, hotkey: string) => Promise<void>
        test_gemini_key: (api_key: string) => Promise<boolean>
        open_url: (url: string) => Promise<void>
        dismiss_connect_banner: () => Promise<void>
        connect_remote_provider: (provider: string) => Promise<{ ok: boolean; error?: string }>
        disconnect_remote_provider: () => Promise<void>
        submit_confirmation: (action: string) => Promise<void>
      }
    }
    __vtbShowConfirmation?: (payload: ConfirmationPayload) => void
  }
}

export interface Category {
  id: number
  name: string
}

export interface Task {
  id: number
  title: string
  description: string
  category_id: number
  category_name: string
  status: string
  created_at: string
  updated_at: string
  due_at_utc: string | null
  due_tz: string | null
  is_full_day: boolean
  lead_time_minutes: number
  recurrence_rule: string | null
  mirror_to_remote: boolean
  external_provider: string | null
  external_id: string | null
  mirror_pending: boolean
  has_drift: boolean
  reminder_fired: boolean
}

export interface ArchivedTask {
  id: number
  title: string
  description: string
  category_name: string
  status: string
  due_at_utc: string | null
  mirror_to_remote: number
  external_provider: string | null
  created_at: string
  archived_at: string
}

export interface ConfirmationPayload {
  title: string
  due: string | null
  category: string
  mirror: boolean
  timeout: number
}

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
