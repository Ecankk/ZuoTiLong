import type { ReactNode } from 'react'
import { cx } from '../../lib/cx'
import styles from './ButtonRow.module.css'

/** 一排相邻的按钮或链接：统一间距，放不下时换行。`align="end"` 靠右。 */
export function ButtonRow({
  children,
  align = 'start',
  className,
}: {
  children: ReactNode
  align?: 'start' | 'end' | 'between'
  className?: string
}) {
  return <div className={cx(styles.row, styles[align], className)}>{children}</div>
}
