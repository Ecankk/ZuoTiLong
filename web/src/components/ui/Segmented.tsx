import * as ToggleGroup from '@radix-ui/react-toggle-group'
import { NavLink } from 'react-router'
import styles from './Segmented.module.css'

type Item<T extends string> = { value: T; label: string }

/** 同一页面内的视图切换，如“按考点 / 按试卷”。 */
export function Segmented<T extends string>({
  label,
  items,
  value,
  onChange,
}: {
  label: string
  items: Item<T>[]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <ToggleGroup.Root
      type="single"
      aria-label={label}
      className={styles.root}
      value={value}
      onValueChange={(next) => next && onChange(next as T)}
    >
      {items.map((item) => (
        <ToggleGroup.Item key={item.value} value={item.value} className={styles.item}>
          {item.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  )
}

/** 外观同 Segmented 的子页面导航，如单卷的“概览 / 逐题分析 / 本卷总结”。 */
export function SegmentedLinks({
  label,
  links,
}: {
  label: string
  links: { to: string; label: string; end?: boolean }[]
}) {
  return (
    <nav aria-label={label} className={styles.root}>
      {links.map((link) => (
        <NavLink key={link.to} to={link.to} end={link.end} className={styles.item}>
          {link.label}
        </NavLink>
      ))}
    </nav>
  )
}
