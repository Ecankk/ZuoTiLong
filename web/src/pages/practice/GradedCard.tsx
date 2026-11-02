import { BookOpen, Check, Upload } from 'lucide-react'
import type { PracticeGroup, PracticeResponse } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Button, ButtonLink } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip, CorrectnessChip } from '../../components/ui/Chip'
import { Fold } from '../../components/ui/Fold'
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

/** 作答照片沿用旧的图片入口 */
const answerImageUrl = (id: string) => `/api/answer-images/${encodeURIComponent(id)}`

export function GradedCard({
  detail,
  position,
  group,
  note,
}: {
  detail: PracticeResponse
  position: { index: number; total: number }
  group: PracticeGroup
  /** 练习已停用时的说明 */
  note?: string
}) {
  const { practice, latest_attempt: attempt } = detail
  const assessment = attempt?.assessment
  if (!attempt || !assessment) return null
  const correctness = assessmentCorrectness(assessment)
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
          {note && <p className={styles.stopped}>{note}</p>}
          {detail.question?.question_image && (
            <img
              className={styles.questionImage}
              src={detail.question.question_image}
              alt="练习原题"
            />
          )}
          {detail.question?.question_text && (
            <div className={cx('read', styles.question)}>
              <MathText text={detail.question.question_text} />
            </div>
          )}
          <div className={cx(styles.mine, photoCount === 0 && styles.noPhoto)}>
            {photoCount > 0 && (
              <a href={answerImageUrl(attempt.image_ids[0])} target="_blank" rel="noreferrer">
                <img
                  className={styles.minePhoto}
                  src={answerImageUrl(attempt.image_ids[0])}
                  alt="你的作答照片"
                />
              </a>
            )}
            <div>
              <small>你的作答{photoCount > 0 && `（照片 ${photoCount} 张）`}</small>
              <div className="read">
                <MathText text={attempt.response || '只提交了照片'} />
              </div>
            </div>
          </div>
          {!note && (
            <div className={styles.gradedActions}>
              <Button size="sm" disabled title="补充作答即将开放">
                <Upload size={16} aria-hidden />
                补充步骤或照片
              </Button>
              <Button size="sm" variant="ghost" disabled title="查看解析即将开放">
                <BookOpen size={16} aria-hidden />
                查看参考解析
              </Button>
              <span className={styles.soon}>补充作答和查看解析即将开放</span>
            </div>
          )}
        </div>

        <div className={styles.feedback}>
          <div className={cx(styles.feedbackTop, styles[correctness])}>
            <CorrectnessChip value={correctness} />
            <h3>批改反馈</h3>
          </div>
          <div className={cx('read', styles.feedbackBody)}>
            <p className={styles.feedbackSection}>
              <MathText text={assessment.feedback} />
            </p>
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
