import { useState, useEffect } from 'react'
import { ChevronDown, ChevronUp, Check } from 'lucide-react'
import type { Task } from '@/types/domain'
import { api } from '@/api'
import '../styles/RecurringDoneCard.css'

interface Occurrence {
  id: number
  due_at_utc: string
  fired: number
  is_done: number
}

interface RecurringDoneCardProps {
  task: Task
}

export const RecurringDoneCard = ({ task }: RecurringDoneCardProps) => {
  const [isExpanded, setIsExpanded] = useState(false)
  const [occurrences, setOccurrences] = useState<Occurrence[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (isExpanded && !loading && occurrences.length === 0) {
      loadOccurrences()
    }
  }, [isExpanded])

  const loadOccurrences = async () => {
    setLoading(true)
    try {
      const occs = await api.getOccurrences(task.id)
      setOccurrences(occs)
    } catch (e) {
      console.error('Failed to load occurrences', e)
    } finally {
      setLoading(false)
    }
  }

  const doneOccurrences = occurrences.filter(o => o.is_done === 1)
  const totalOccurrences = occurrences.length

  if (totalOccurrences === 0) {
    return null
  }

  const formatDate = (dateStr: string) => {
    try {
      const date = new Date(dateStr + 'Z')
      return date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: date.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined,
      })
    } catch {
      return dateStr
    }
  }

  return (
    <div className="recurring-done-card">
      <button
        className="done-card-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="done-card-header-content">
          <Check size={16} className="done-icon" />
          <span className="done-label">
            {doneOccurrences.length} of {totalOccurrences} completed
          </span>
        </div>
        <div className="done-card-toggle">
          {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </button>

      {isExpanded && (
        <div className="done-card-content">
          {loading ? (
            <p className="done-card-loading">Loading...</p>
          ) : doneOccurrences.length === 0 ? (
            <p className="done-card-empty">No completed occurrences yet</p>
          ) : (
            <div className="done-card-list">
              {doneOccurrences.map(occ => (
                <div key={occ.id} className="done-item">
                  <Check size={12} className="done-item-icon" />
                  <span className="done-item-date">
                    {formatDate(occ.due_at_utc)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
