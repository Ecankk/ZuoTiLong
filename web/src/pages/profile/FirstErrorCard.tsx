import { Link } from 'react-router'
import type { FirstErrorSummary } from '../../api/types'
import { Card } from '../../components/ui/Card'
import { firstErrorLink, stageLabel } from '../../lib/profile'
import styles from './FirstErrorCard.module.css'

/**
 * 近期错题最常卡在哪一步：后端满足门槛才给（否则 null，不显示这张卡），
 * 结论句直接用后端的 statement，前端不自己拼；下面最多 3 道可以点开核对的题。
 */
export function FirstErrorCard({
  summary,
  className,
}: {
  summary: FirstErrorSummary | null | undefined
  className?: string
}) {
  if (!summary) return null
  const items = summary.evidence.slice(0, 3)
  return (
    <Card padded className={className} aria-label="最常错在哪一步">
      <h2 className={styles.title}>最常错在哪一步</h2>
      <p className={styles.statement}>{summary.statement}</p>
      {items.length > 0 && (
        <ul className={styles.items} aria-label="可以点开看的题">
          {items.map((e, i) => {
            const to = firstErrorLink(e)
            const stage = stageLabel(e.first_error_stage)
            const where = e.label
              ? e.label
              : e.question_number
                ? `第 ${e.question_number} 题`
                : e.source === 'exam'
                  ? '原卷题目'
                  : '练习题'
            const body = (
              <>
                <span className={styles.where}>
                  {where}
                  {stage && <em>先错在{stage}</em>}
                </span>
                {e.first_error_evidence && (
                  <span className={styles.why}>{e.first_error_evidence}</span>
                )}
              </>
            )
            return (
              <li key={e.attempt_id ?? e.question_id ?? i}>
                {to ? <Link to={to}>{body}</Link> : <div>{body}</div>}
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
