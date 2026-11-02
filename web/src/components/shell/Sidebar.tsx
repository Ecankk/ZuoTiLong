import {
  ChartNoAxesColumn,
  FileText,
  House,
  Library,
  ListTree,
  PencilLine,
  SlidersHorizontal,
  type LucideIcon,
} from 'lucide-react'
import { NavLink } from 'react-router'
import { usePractices, usePreferences } from '../../api/queries'
import { mathTypeName } from '../../lib/labels'
import { BackgroundIndicator } from './BackgroundIndicator'
import styles from './Sidebar.module.css'

type NavEntry = { to: string; label: string; icon: LucideIcon; end?: boolean }

const mainNav: NavEntry[] = [
  { to: '/', label: '首页', icon: House, end: true },
  { to: '/papers', label: '试卷', icon: FileText },
  { to: '/practice', label: '练习', icon: PencilLine },
  { to: '/topics', label: '考点', icon: ListTree },
  { to: '/profile', label: '画像', icon: ChartNoAxesColumn },
  { to: '/bank', label: '题库', icon: Library },
]

function NavItem({ entry, badge }: { entry: NavEntry; badge?: number }) {
  const Icon = entry.icon
  return (
    <NavLink to={entry.to} end={entry.end} className={styles.item}>
      <Icon size={18} strokeWidth={1.8} aria-hidden />
      <span>{entry.label}</span>
      {badge ? <span className={styles.badge}>{badge}</span> : null}
    </NavLink>
  )
}

export function Sidebar() {
  const practice = usePractices('topic')
  const todo = practice.data?.counts.pending
  const { data: preferences } = usePreferences()
  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <img src="/brand/logo-round.png" alt="" />
        <div>
          <strong className={styles.brandName}>做题龙</strong>
          <small className={styles.brandSub}>
            {preferences ? `${mathTypeName(preferences.study_type)} · ` : ''}考研复习
          </small>
        </div>
      </div>
      <nav aria-label="主导航" className={styles.nav}>
        {mainNav.map((entry) => (
          <NavItem
            key={entry.to}
            entry={entry}
            badge={entry.to === '/practice' ? todo : undefined}
          />
        ))}
      </nav>
      <div className={styles.spacer} />
      <div className={`${styles.nav} ${styles.bottom}`}>
        <NavItem entry={{ to: '/settings', label: '设置', icon: SlidersHorizontal }} />
      </div>
      <BackgroundIndicator />
    </aside>
  )
}
