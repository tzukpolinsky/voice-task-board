import { useState } from 'react'
import { Check } from 'lucide-react'
import type { Task } from '@/types/domain'
import { api } from '@/api'
import { useToast } from '@/context/ToastContext'
import '../styles/RecurringCompleteButton.css'

interface RecurringCompleteButtonProps {
  task: Task
  onChanged: () => void
}

export const RecurringCompleteButton = ({ task, onChanged }: RecurringCompleteButtonProps) => {
  const toast = useToast()
  const [showPopover, setShowPopover] = useState(false)

  const handleCompleteInstance = async () => {
    try {
      await api.completeOccurrenceChoice(task.id, 'instance')
      setShowPopover(false)
      onChanged()
    } catch (e) {
      console.error('Failed to complete occurrence', e)
      toast.show(e instanceof Error ? e.message : 'Failed to complete occurrence')
    }
  }

  const handleCompleteSeries = async () => {
    try {
      await api.completeOccurrenceChoice(task.id, 'series')
      setShowPopover(false)
      onChanged()
    } catch (e) {
      console.error('Failed to complete series', e)
      toast.show(e instanceof Error ? e.message : 'Failed to complete series')
    }
  }

  return (
    <div className="recurring-complete-wrapper">
      <button
        className="task-card-action task-card-action--success"
        onClick={() => setShowPopover(!showPopover)}
        title="Mark done"
      >
        <Check size={14} />
      </button>
      
      {showPopover && (
        <div className="recurring-complete-popover">
          <div className="popover-content">
            <p className="popover-title">Complete this task</p>
            <button className="popover-option popover-option--instance" onClick={handleCompleteInstance}>
              <span className="option-label">Mark this occurrence done</span>
              <span className="option-desc">Next will appear tomorrow</span>
            </button>
            <button className="popover-option popover-option--series" onClick={handleCompleteSeries}>
              <span className="option-label">End this series</span>
              <span className="option-desc">No more will appear</span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
