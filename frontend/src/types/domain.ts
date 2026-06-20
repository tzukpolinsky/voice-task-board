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
  recurrence_until: string | null
  is_recurrence: boolean
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

export interface Config {
  gemini_api_key: string | null
  hotkey: string
  remote_provider: string | null
  connect_banner_dismissed: boolean
  // True when Windows DPAPI was unavailable, so secrets could not be saved
  // encrypted (and were therefore not persisted at all).
  encryption_unavailable?: boolean
}
