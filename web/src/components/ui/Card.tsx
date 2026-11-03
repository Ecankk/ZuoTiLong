import type { HTMLAttributes } from 'react'
import { cx } from '../../lib/cx'
import styles from './Card.module.css'

/** 不透明卡片：细描边 + 柔和阴影。 */
export function Card({
  padded = false,
  className,
  ...props
}: { padded?: boolean } & HTMLAttributes<HTMLElement>) {
  return <section className={cx(styles.card, padded && styles.padded, className)} {...props} />
}
