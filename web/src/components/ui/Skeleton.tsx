import { cx } from '../../lib/cx'
import { Card } from './Card'
import styles from './Skeleton.module.css'

/**
 * 加载占位，代替空白的 `return null`：
 * - `card`：一张卡片（标题 + 几行文字），默认
 * - `rows`：列表行，`rows` 指定行数
 * - `question`：题目块（题干 + 大图区域）
 * 读屏只读到一次“正在读取…”。
 */
export function Skeleton({
  variant = 'card',
  rows = 3,
  className,
}: {
  variant?: 'card' | 'rows' | 'question'
  rows?: number
  className?: string
}) {
  const lines = Array.from({ length: rows }, (_, i) => i)
  const content =
    variant === 'rows' ? (
      lines.map((i) => (
        <div key={i} className={styles.row}>
          <span className={cx(styles.bar, styles.dot)} />
          <span className={styles.rowText}>
            <span className={styles.bar} style={{ width: `${70 - (i % 3) * 12}%` }} />
            <span className={cx(styles.bar, styles.small)} style={{ width: '38%' }} />
          </span>
        </div>
      ))
    ) : variant === 'question' ? (
      <>
        <span className={cx(styles.bar, styles.title)} />
        <span className={styles.bar} />
        <span className={styles.bar} style={{ width: '82%' }} />
        <span className={styles.block} />
      </>
    ) : (
      <>
        <span className={cx(styles.bar, styles.title)} />
        {lines.map((i) => (
          <span key={i} className={styles.bar} style={{ width: `${92 - (i % 3) * 14}%` }} />
        ))}
      </>
    )
  return (
    <Card padded className={cx(styles.skeleton, className)} aria-busy="true">
      <span className={styles.sr} role="status">
        正在读取…
      </span>
      <div className={styles.stack} aria-hidden>
        {content}
      </div>
    </Card>
  )
}
