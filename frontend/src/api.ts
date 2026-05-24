declare global {
  interface Window {
    pywebview?: {
      api: {
        get_tasks: () => Promise<Task[]>
        get_categories: () => Promise<Category[]>
        add_category: (name: string) => Promise<number>
        delete_category: (id: number) => Promise<void>
        move_task: (task_id: number, category_id: number) => Promise<void>
        delete_task: (task_id: number) => Promise<void>
        create_task: (title: string, category_id: number, description?: string) => Promise<number>
        update_task: (task_id: number, title?: string | null, description?: string | null) => Promise<boolean>
        get_config: () => Promise<{ gemini_api_key: string | null; hotkey: string }>
        save_config: (api_key: string, hotkey: string) => Promise<void>
        test_gemini_key: (api_key: string) => Promise<boolean>
        open_url: (url: string) => Promise<void>
      }
    }
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
}

export const api = {
  getTasks: async (): Promise<Task[]> => {
    return window.pywebview?.api.get_tasks() ?? []
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

  createTask: async (title: string, categoryId: number, description: string = ''): Promise<number> => {
    return window.pywebview?.api.create_task(title, categoryId, description) ?? 0
  },

  updateTask: async (taskId: number, title?: string | null, description?: string | null): Promise<boolean> => {
    return window.pywebview?.api.update_task(taskId, title, description) ?? false
  },
}
