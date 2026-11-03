import { useState } from 'react'
import { endpoints } from '../../api/endpoints'
import { useAction, usePaper } from '../../api/queries'
import type { QuestionResponse } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import styles from './QuestionAnalysisPage.module.css'

/**
 * 请做题龙重新核对这道题（沿用 POST /api/questions/{id}/review）。
 * 待核对或看不清作答的题默认展开说明。
 */
export function ReviewCard({ paperId, detail }: { paperId: string; detail: QuestionResponse }) {
  const { data: paper } = usePaper(paperId)
  const [note, setNote] = useState('')
  const review = useAction(
    () => endpoints.reviewQuestion(detail.question.id, paper?.analysis.report_id ?? '', note),
    [['tasks'], ['questions']],
  )
  const reportId = paper?.analysis.report_id
  if (!paper || !reportId || paper.paper.archived_at) return null
  const unclear =
    detail.question.correctness === 'unknown' ||
    detail.diagnosis?.answer_evidence?.student_state === 'unreadable'
  return (
    <Card padded className={styles.review} aria-label="重新核对">
      <h3>{unclear ? '这道题需要核对' : '对这道题的分析有疑问？'}</h3>
      <p>
        做题龙会重新看这道题的原卷再给出结论。可以写下要它注意的地方，不写也可以；旧的分析会保留。
      </p>
      <textarea
        className={styles.reviewNote}
        maxLength={4000}
        placeholder="例如：最后选的是 D，涂改前是 B。"
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      <div className={styles.reviewActions}>
        <Button
          variant={unclear ? 'primary' : 'secondary'}
          disabled={review.isPending || review.isSuccess}
          onClick={() => review.mutate(undefined)}
        >
          请做题龙重新核对
        </Button>
        {review.isSuccess && <span className={styles.ok}>已提交，核对完成后结果会更新。</span>}
        {review.error && <span className={styles.errorText}>{review.error.message}</span>}
      </div>
    </Card>
  )
}
