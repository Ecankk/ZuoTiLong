import { NavLink } from 'react-router'
import type { QuestionSummary } from '../../api/types'
import { Card } from '../../components/ui/Card'
import { cx } from '../../lib/cx'
import { correctnessLabel } from '../../lib/labels'
import { groupQuestions } from '../../lib/questions'
import styles from './QuestionStrip.module.css'

/**
 * 题号条。没有分析结果的题显示为虚线：本卷正在分析时标“分析中”（进行中用主色），
 * 否则标“暂无分析”。进度只到试卷，不推测具体题号。
 */
export function QuestionStrip({
  paperId,
  questions,
  analyzing,
}: {
  paperId: string
  questions: QuestionSummary[]
  analyzing: boolean
}) {
  const pendingLabel = analyzing ? '分析中' : '暂无分析'
  const status = (question: QuestionSummary) =>
    question.analysis_available ? correctnessLabel[question.correctness] : pendingLabel
  const legend = [
    { label: '正确', color: 'var(--status-correct)' },
    { label: '部分正确', color: 'var(--status-partial)' },
    { label: '有误', color: 'var(--status-wrong)' },
    { label: '待核对', color: 'var(--status-unknown)' },
    ...(questions.some((question) => !question.analysis_available)
      ? [{ label: pendingLabel }]
      : []),
  ]
  return (
    <Card className={styles.strip} aria-label="题号">
      {groupQuestions(questions).map((group) => (
        <div key={group.label ?? 'all'}>
          {group.label && <small className={styles.label}>{group.label}</small>}
          <div className={styles.chips}>
            {group.questions.map((question) => (
              <NavLink
                key={question.id}
                to={`/papers/${paperId}/questions/${question.number}`}
                className={cx(
                  styles.chip,
                  question.analysis_available
                    ? styles[question.correctness]
                    : cx(styles.pending, analyzing && styles.analyzing),
                )}
                title={`第 ${question.number} 题 · ${status(question)}`}
              >
                {question.number}
              </NavLink>
            ))}
          </div>
        </div>
      ))}
      <div className={styles.legend}>
        {legend.map((item) => (
          <span key={item.label}>
            <i
              className={
                'color' in item ? undefined : cx(styles.dashed, analyzing && styles.analyzingLegend)
              }
              style={'color' in item ? { background: item.color } : undefined}
            />
            {item.label}
          </span>
        ))}
      </div>
    </Card>
  )
}
