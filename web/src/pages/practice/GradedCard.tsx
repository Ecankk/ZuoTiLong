import { BookOpen, Check, Upload } from 'lucide-react'
import type { PracticeGroup, PracticeResponse } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Button, ButtonLink } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip, CorrectnessChip } from '../../components/ui/Chip'
import { Fold } from '../../components/ui/Fold'
import { PaperPlaceholder } from '../../components/ui/PaperPlaceholder'
import { cx } from '../../lib/cx'
import { assessmentCorrectness, sourceName } from '../../lib/labels'
import styles from './PracticeCard.module.css'

function gradedTime(iso: string) {
  const date = new Date(iso)
  const today = new Date().toDateString() === date.toDateString()
  const time = date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  return `${today ? '今天' : `${date.getMonth() + 1}月${date.getDate()}日`} ${time} 提交`
}

export function GradedCard({
  detail,
  position,
  group,
}: {
  detail: PracticeResponse
  position: { index: number; total: number }
  group: PracticeGroup
}) {
  const { practice, latest_attempt: attempt } = detail
  const assessment = attempt?.assessment
  if (!attempt || !assessment) return null
  const correctness = assessmentCorrectness(assessment.correct)
  const valid = (assessment.observations ?? []).filter((item) => item.status === 'valid')
  const nextIndex = group.items.findIndex((item) => item.status === 'pending')
  const next = nextIndex >= 0 ? group.items[nextIndex] : undefined
  const photoCount = attempt.image_ids.length

  return (
    <Card className={styles.card} aria-label="已批改的练习">
      <div className={styles.split}>
        <div>
          <div className={styles.gradedHead}>
            <Chip>
              第 {position.index} 道 · {sourceName(practice.access)} · 第 {practice.access.number}{' '}
              题
            </Chip>
            <CorrectnessChip value={correctness} />
            <span className={styles.when}>{gradedTime(attempt.created_at)}</span>
          </div>
          {detail.question?.question_text && (
            <div className={cx('read', styles.question)}>
              <MathText text={detail.question.question_text} />
            </div>
          )}
          <div className={cx(styles.mine, photoCount === 0 && styles.noPhoto)}>
            {photoCount > 0 && (
              <PaperPlaceholder
                compact
                className={styles.minePhoto}
                lines={[
                  ['h', 80],
                  ['h', 60],
                  ['h', 88],
                  ['h', 45],
                ]}
              />
            )}
            <div>
              <small>你的作答{photoCount > 0 && `（照片 ${photoCount} 张）`}</small>
              <div className="read">
                <MathText text={attempt.response || '只提交了照片'} />
              </div>
            </div>
          </div>
          <div className={styles.gradedActions}>
            {detail.actions.includes('supplement') && (
              <Button size="sm">
                <Upload size={16} aria-hidden />
                补充步骤或照片
              </Button>
            )}
            {detail.actions.includes('reveal_analysis') && (
              <Button size="sm" variant="ghost">
                <BookOpen size={16} aria-hidden />
                查看参考解析
              </Button>
            )}
          </div>
        </div>

        <div className={styles.feedback}>
          <div className={cx(styles.feedbackTop, styles[correctness])}>
            <CorrectnessChip value={correctness} />
            <h3>
              <MathText text={assessment.feedback} />
            </h3>
          </div>
          <div className={cx('read', styles.feedbackBody)}>
            {valid.length > 0 && (
              <div className={styles.feedbackSection}>
                <h4>做对的部分</h4>
                <ul className={styles.okList}>
                  {valid.map((item, index) => (
                    <li key={index}>
                      <Check size={16} aria-hidden />
                      <span>
                        <MathText text={item.step} />
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {assessment.first_error && (
              <div className={styles.feedbackSection}>
                <h4>首个错误</h4>
                <div className={styles.firstError}>
                  <MathText text={assessment.first_error.step} />
                  {assessment.first_error.evidence && (
                    <small>
                      <MathText text={assessment.first_error.evidence} />
                    </small>
                  )}
                </div>
              </div>
            )}
            {assessment.next_step && (
              <div className={styles.feedbackSection}>
                <h4>接下来</h4>
                <div className={styles.nextStep}>
                  <span>
                    <MathText text={assessment.next_step} />
                  </span>
                  {next && (
                    <ButtonLink size="sm" variant="soft" to={`/practice?item=${next.id}`}>
                      去做第 {nextIndex + 1} 道
                    </ButtonLink>
                  )}
                </div>
              </div>
            )}
            {assessment.reference_reasoning && (
              <Fold title="参考推导">
                <MathText text={assessment.reference_reasoning} />
              </Fold>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}
