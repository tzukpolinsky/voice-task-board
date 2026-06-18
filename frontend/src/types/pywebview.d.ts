import type {
  Task,
  ArchivedTask,
  Category,
  Config,
  ConfirmationPayload,
} from './domain'

interface PywebviewApi {
  // Tasks
  get_tasks(include_done?: boolean): Promise<Task[]>
  create_task(
    title: string,
    category_id: number,
    description?: string,
    due_at_utc?: string | null,
    due_tz?: string | null,
    is_full_day?: boolean,
    lead_time_minutes?: number,
    recurrence_rule?: string | null,
    mirror_to_remote?: boolean,
  ): Promise<number>
  update_task(
    task_id: number,
    title?: string | null,
    description?: string | null,
  ): Promise<boolean>
  update_task_due(
    task_id: number,
    due_at_utc: string | null,
    due_tz: string | null,
    is_full_day: boolean,
    lead_time_minutes: number,
    recurrence_rule?: string | null,
  ): Promise<void>
  delete_task(task_id: number): Promise<void>
  complete_task(task_id: number): Promise<void>
  move_task(task_id: number, category_id: number): Promise<void>
  set_mirror(task_id: number, mirror: boolean): Promise<void>
  get_archived_tasks(
    category_name?: string | null,
    limit?: number,
    offset?: number,
  ): Promise<ArchivedTask[]>

  // Categories
  get_categories(): Promise<Category[]>
  add_category(name: string): Promise<number>
  rename_category(id: number, name: string): Promise<void>
  delete_category(id: number): Promise<void>

  // Config / remote
  get_config(): Promise<Config | null>
  save_config(api_key: string, hotkey: string): Promise<void>
  test_gemini_key(api_key: string): Promise<boolean>
  get_pending_mirror_count(): Promise<number>
  dismiss_connect_banner(): Promise<void>
  connect_remote_provider(provider: string): Promise<{ ok: boolean; error?: string }>
  disconnect_remote_provider(): Promise<void>
  submit_confirmation(action: string): Promise<void>
  open_url(url: string): Promise<void>

  // Occurrences / Recurrence
  complete_occurrence_choice(task_id: number, scope: 'instance' | 'series'): Promise<void>
  get_occurrences(task_id: number): Promise<Array<{ id: number; due_at_utc: string; fired: number; is_done: number }>>
  set_recurrence(task_id: number, repeat_text: string | null, until: string | null): Promise<void>
}

declare global {
  interface Window {
    pywebview?: { api: PywebviewApi }
    __vtbShowConfirmation?: (payload: ConfirmationPayload) => void
    __vtbDataChanged?: () => void
  }
}

export {}
