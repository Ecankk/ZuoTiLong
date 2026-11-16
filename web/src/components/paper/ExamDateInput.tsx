import { useId } from 'react'
import { thisMonth, todayDay, type DateChoice, type DateMode } from '../../lib/examDate'
import styles from './ExamDateInput.module.css'

const modes: { value: DateMode; label: string }[] = [
  { value: 'none', label: '不填' },
  { value: 'day', label: '具体日期' },
  { value: 'month', label: '约某月' },
  { value: 'forgotten', label: '记不清' },
]

/**
 * 作答日期：先选怎么填，再填日子或月份。默认“不填”，不会自动填今天；
 * “今天”只是具体日期旁边一个由用户主动点的按钮。
 */
export function ExamDateInput({
  value,
  onChange,
  label = '作答日期',
  noneLabel = '不填',
  compact = false,
}: {
  value: DateChoice
  onChange: (value: DateChoice) => void
  label?: string
  noneLabel?: string
  compact?: boolean
}) {
  const id = useId()
  const setMode = (mode: DateMode) => {
    // 在“具体日期”和“约某月”之间切换时保留已填的年月
    const carried = mode === 'month' && value.mode === 'day' ? value.value.slice(0, 7) : ''
    onChange({ mode, value: mode === 'day' || mode === 'month' ? carried : '' })
  }
  return (
    <div className={styles.root} data-compact={compact || undefined}>
      <label className={styles.label} htmlFor={`${id}-mode`}>
        {label}
      </label>
      <div className={styles.row}>
        <select
          id={`${id}-mode`}
          value={value.mode}
          onChange={(event) => setMode(event.target.value as DateMode)}
        >
          {modes.map((mode) => (
            <option key={mode.value} value={mode.value}>
              {mode.value === 'none' ? noneLabel : mode.label}
            </option>
          ))}
        </select>
        {value.mode === 'day' && (
          <>
            <input
              type="date"
              aria-label={`${label}：哪一天`}
              value={value.value}
              max={todayDay()}
              onChange={(event) => onChange({ mode: 'day', value: event.target.value })}
            />
            <button
              type="button"
              className={styles.today}
              onClick={() => onChange({ mode: 'day', value: todayDay() })}
            >
              今天
            </button>
          </>
        )}
        {value.mode === 'month' && (
          <input
            type="month"
            aria-label={`${label}：大约哪个月`}
            value={value.value}
            max={thisMonth()}
            onChange={(event) => onChange({ mode: 'month', value: event.target.value })}
          />
        )}
      </div>
    </div>
  )
}
