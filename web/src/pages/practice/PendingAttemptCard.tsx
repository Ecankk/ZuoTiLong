import { Upload } from 'lucide-react'
import { useState } from 'react'
import { endpoints } from '../../api/endpoints'
import { useAction, useTasks } from '../../api/queries'
import type { PracticeCard, PracticeResponse } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip } from '../../components/ui/Chip'
import { cx } from '../../lib/cx'
import { practiceSource } from '../../lib/labels'
import { QuestionContent } from './AnswerCard'
import { AttemptForm } from './AttemptForm'
import { ReferenceAnalysis, SubmittedAttempt } from './GradedCard'
import { RevealButton } from './RevealButton'
import styles from './PracticeCard.module.css'

/** 已提交、还没有批改结果的作答：批改中，或需要重新排入批改。 */
export function PendingAttemptCard({
  card,
  detail,
  position,
}: {
  card: PracticeCard
  detail: PracticeResponse
  position: { index: number; total: number }
}) {
  const { data: tasks } = useTasks()
  const [supplementing, setSupplementing] = useState(false)
  const attempt = detail.latest_attempt
  const regrade = useAction(
    () => endpoints.requestGrading(card.id, attempt?.id ?? ''),
    [['practices'], ['tasks']],
  )
  if (!attempt) return null
  const grading = card.status === 'grading'
  const unavailable = tasks?.availability.status === 'unavailable'
  return (
    <Card className={styles.card} aria-label="批改中的练习">
      <div className={styles.gradedHead}>
        <Chip>
          第 {position.index} 道{practiceSource(card.access) && ` · ${practiceSource(card.access)}`}
        </Chip>
        <Chip tone="primary">{grading ? '批改中' : '等待批改'}</Chip>
      </div>
      <QuestionContent question={detail.question} />
      <SubmittedAttempt attempt={attempt} />
      {grading ? (
        <div className={cx(styles.pendingStatus, unavailable && styles.warn)} role="status">
          {!unavailable && <span className={styles.spinner} aria-hidden />}
          {unavailable
            ? '作答已保存。做题龙还不能开始工作，准备好 AI 服务后会自动批改。'
            : '做题龙正在批改，一般 1～2 分钟出结果。'}
        </div>
      ) : (
        <div className={styles.pendingStatus} role="status">
          作答已保存，还没有批改结果。
          <Button size="sm" disabled={regrade.isPending} onClick={() => regrade.mutate(undefined)}>
            请做题龙批改
          </Button>
        </div>
      )}
      {regrade.error && <p className={styles.formError}>{regrade.error.message}</p>}
      <div className={styles.gradedActions}>
        {detail.actions.includes('supplement') && !supplementing && (
          <Button size="sm" onClick={() => setSupplementing(true)}>
            <Upload size={16} aria-hidden />
            补充步骤或照片
          </Button>
        )}
        {detail.actions.includes('reveal_analysis') && (
          <RevealButton bankId={card.bank_id} kind="analysis" label="查看参考解析" variant="ghost">
            查看后会记下“看过解析”。之后的补充作答会和独立完成的作答分开统计。
          </RevealButton>
        )}
      </div>
      {supplementing && (
        <>
          <AttemptForm
            practiceId={card.id}
            attemptId={attempt.id}
            showExposure={false}
            onSubmitted={() => setSupplementing(false)}
          />
          <Button size="sm" variant="ghost" onClick={() => setSupplementing(false)}>
            取消补充
          </Button>
        </>
      )}
      <ReferenceAnalysis detail={detail} />
    </Card>
  )
}
