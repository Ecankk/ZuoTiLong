import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'
import styles from './Fold.module.css'

/** 默认折叠的次要内容，如可能原因、参考推导。 */
export function Fold({
  title,
  hint,
  defaultOpen = false,
  children,
}: {
  title: string
  hint?: string
  defaultOpen?: boolean
  children: ReactNode
}) {
  return (
    <details className={styles.fold} open={defaultOpen}>
      <summary className={styles.summary}>
        <ChevronRight size={16} className={styles.chevron} aria-hidden />
        {title}
        {hint && <small className={styles.hint}>{hint}</small>}
      </summary>
      <div className={styles.body}>{children}</div>
    </details>
  )
}
