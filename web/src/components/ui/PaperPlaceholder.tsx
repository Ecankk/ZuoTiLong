import type { CSSProperties } from 'react'
import { cx } from '../../lib/cx'
import styles from './PaperPlaceholder.module.css'

/** 每项：印刷行 p、手写行 h、红笔 r、空行 gap，后跟宽度百分比。 */
export type PaperLine = ['p' | 'h' | 'r', number, number?] | ['gap']

/**
 * 原卷/作答图的占位。接入真实切图前使用；有真实图片后替换为 <img>。
 */
export function PaperPlaceholder({
  lines,
  caption,
  compact = false,
  className,
  style,
}: {
  lines: PaperLine[]
  caption?: string
  compact?: boolean
  className?: string
  style?: CSSProperties
}) {
  return (
    <div
      className={cx(styles.paper, compact && styles.compact, className)}
      style={style}
      aria-hidden
    >
      {lines.map((line, index) => {
        if (line[0] === 'gap') return <div key={index} className={styles.gap} />
        const [kind, width, offset = 0] = line
        return (
          <div
            key={index}
            className={cx(styles.line, kind === 'h' && styles.hand, kind === 'r' && styles.red)}
            style={{ width: `${width}%`, marginLeft: `${offset}%` }}
          />
        )
      })}
      {caption && <span className={styles.caption}>{caption}</span>}
    </div>
  )
}
