import { useState } from 'react'
import '../styles/RecurrenceSelect.css'

interface RecurrenceSelectProps {
  value: string | null
  until: string | null
  onChange: (repeat: string | null, until: string | null) => void
  disabled?: boolean
}

const RECURRENCE_PRESETS = [
  { label: 'None', value: null },
  { label: 'Every day', value: 'every day' },
  { label: 'Weekdays', value: 'weekdays' },
  { label: 'Every Monday', value: 'every monday' },
  { label: 'Every Tuesday', value: 'every tuesday' },
  { label: 'Every Wednesday', value: 'every wednesday' },
  { label: 'Every Thursday', value: 'every thursday' },
  { label: 'Every Friday', value: 'every friday' },
  { label: 'Every Saturday', value: 'every saturday' },
  { label: 'Every Sunday', value: 'every sunday' },
  { label: 'Every week', value: 'every week' },
  { label: 'Every 2 weeks', value: 'every 2 weeks' },
  { label: 'Every month', value: 'every month' },
  { label: 'Every year', value: 'every year' },
  { label: 'Custom...', value: '__custom__' },
]

export function RecurrenceSelect({ value, until, onChange, disabled = false }: RecurrenceSelectProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [customText, setCustomText] = useState('')
  const [showUntilInput, setShowUntilInput] = useState(false)

  // Filter presets based on search
  const filtered = RECURRENCE_PRESETS.filter(p =>
    p.label.toLowerCase().includes(searchText.toLowerCase())
  )

  const selectedLabel = value 
    ? RECURRENCE_PRESETS.find(p => p.value === value)?.label || 'Custom'
    : 'None'

  const handleSelectPreset = (preset: typeof RECURRENCE_PRESETS[0]) => {
    if (preset.value === '__custom__') {
      // Custom option - show text input instead
      setCustomText(value || '')
      setShowUntilInput(true)
    } else {
      // Regular preset
      onChange(preset.value, until)
      setIsOpen(false)
      setSearchText('')
      setShowUntilInput(false)
    }
  }

  const handleCustomSave = () => {
    if (customText.trim()) {
      onChange(customText, until)
      setIsOpen(false)
      setSearchText('')
      setCustomText('')
    }
  }

  const handleCustomCancel = () => {
    setShowUntilInput(false)
    setCustomText('')
    setSearchText('')
  }

  const handleUntilChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newUntil = e.target.value || null
    onChange(value, newUntil)
  }

  return (
    <div className="recurrence-select">
      <label>Repeats</label>

      <div className="recurrence-trigger">
        <button
          className="recurrence-button"
          onClick={() => setIsOpen(!isOpen)}
          disabled={disabled}
        >
          {selectedLabel}
          <span className="dropdown-icon">▼</span>
        </button>
      </div>

      {isOpen && (
        <div className="recurrence-dropdown">
          {!showUntilInput ? (
            <>
              <input
                type="text"
                className="recurrence-search"
                placeholder="Search repeats..."
                value={searchText}
                onChange={e => setSearchText(e.target.value)}
                autoFocus
              />

              <div className="recurrence-options">
                {filtered.map(preset => (
                  <button
                    key={preset.value}
                    className={`recurrence-option ${value === preset.value ? 'selected' : ''}`}
                    onClick={() => handleSelectPreset(preset)}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <div className="custom-repeat-input">
              <input
                type="text"
                className="custom-text-input"
                placeholder="e.g., every monday at 9:30 AM"
                value={customText}
                onChange={e => setCustomText(e.target.value)}
                autoFocus
              />
              <div className="custom-buttons">
                <button className="save-btn" onClick={handleCustomSave}>Save</button>
                <button className="cancel-btn" onClick={handleCustomCancel}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}

      {value && (
        <div className="until-input-group">
          <label>Until (optional)</label>
          <input
            type="date"
            className="until-input"
            value={until || ''}
            onChange={handleUntilChange}
            disabled={disabled}
          />
        </div>
      )}
    </div>
  )
}
