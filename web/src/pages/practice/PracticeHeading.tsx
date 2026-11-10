import type { ReactNode } from 'react'
import type { PracticeResponse } from '../../api/types'
import { Chip } from '../../components/ui/Chip'
import { practiceSource } from '../../lib/labels'
import { originLabel, practiceOrigin, splitQuestionText } from './selection'
import styles from './PracticeCard.module.css'

/**
 * 练习卡片的标题，三种卡片（作答、批改中、已批改）共用：
 * 上面一行“考点 · 第 i / n 道”，标题只写出处，章节（如“参数估计”）放在标题后面，不再重复显示。
 */
export function PracticeHeading({
  detail,
  eyebrow,
  children,
}: {
  detail: PracticeResponse
  eyebrow: string
  /** 标题右侧的状态，如正误、提交时间 */
  children?: ReactNode
}) {
  const { practice } = detail
  const chapter = detail.question ? splitQuestionText(detail.question).chapter : null
  const origin = practiceOrigin(practice)
  return (
    <header className={styles.heading}>
      <div className={styles.headingText}>
        <p className={styles.eyebrow}>
          {eyebrow}
          {origin && origin !== 'paper' && (
            <Chip tone="primary" className={styles.originChip}>
              {originLabel[origin]}
            </Chip>
          )}
        </p>
        <h2>
          {practiceSource(practice.access) || '练习题'}
          {chapter && <small className={styles.chapter}>{chapter}</small>}
        </h2>
      </div>
      {children && <div className={styles.headingSide}>{children}</div>}
    </header>
  )
}
