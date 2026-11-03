import { ChevronRight } from 'lucide-react'
import { Fragment, type ReactNode } from 'react'
import { Link } from 'react-router'
import styles from './PageHeader.module.css'

export function PageHeader({
  title,
  eyebrow,
  crumbs,
  subtitle,
  actions,
}: {
  title: ReactNode
  eyebrow?: string
  crumbs?: { label: string; to?: string }[]
  subtitle?: ReactNode
  actions?: ReactNode
}) {
  return (
    <header className={styles.header}>
      <div>
        {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
        {crumbs && (
          <nav aria-label="位置" className={styles.crumbs}>
            {crumbs.map((crumb, index) => (
              <Fragment key={crumb.label}>
                {index > 0 && <ChevronRight size={14} aria-hidden />}
                {crumb.to ? <Link to={crumb.to}>{crumb.label}</Link> : <span>{crumb.label}</span>}
              </Fragment>
            ))}
          </nav>
        )}
        <h1>{title}</h1>
        {subtitle && <div className={styles.subtitle}>{subtitle}</div>}
      </div>
      {actions}
    </header>
  )
}
