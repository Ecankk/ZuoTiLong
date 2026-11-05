import { Check, Upload } from 'lucide-react'
import { useState } from 'react'
import type { Attempt, PracticeGroup, PracticeResponse } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Button, ButtonLink } from '../../components/ui/Button'
import { practiceLink } from '../bank/BankQuestion'
import { Card } from '../../components/ui/Card'
import { Chip, CorrectnessChip } from '../../components/ui/Chip'
import { Fold } from '../../components/ui/Fold'
import { cx } from '../../lib/cx'
import { assessmentCorrectness, sourceName } from '../../lib/labels'
import { QuestionContent } from './AnswerCard'
import { AttemptForm } from './AttemptForm'
import { RevealButton } from './RevealButton'
import styles from './PracticeCard.module.css'

/** 作答照片沿用旧的图片入口 */
export const answerImageUrl = (id: string) => `/api/answer-images/${encodeURIComponent(id)}`

const roleLabel: Record<string, string> = {
  own_work: '我的作答',
  marking: '事后批改',
  external_solution: '参考解析',
}

function submittedTime(iso: string) {
  const date = new Date(iso)
  const today = new Date().toDateString() === date.toDateString()
  const time = date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  return `${today ? '今天' : `${date.getMonth() + 1}月${date.getDate()}日`} ${time} 提交`
}

/** 已提交的作答：文字与照片。 */
export function SubmittedAttempt({ attempt }: { attempt: Attempt }) {
  return (
    <div className={styles.mineBlock}>
      <small className={styles.mineLabel}>
        你的作答{attempt.image_ids.length > 0 && `（照片 ${attempt.image_ids.length} 张）`}
      </small>
      {attempt.response && (
        <div className="read">
          <MathText text={attempt.response} />
        </div>
      )}
      {attempt.image_ids.length > 0 && (
        <div className={styles.photos}>
          {attempt.image_ids.map((id) => (
            <a
              key={id}
              className={styles.thumb}
              href={answerImageUrl(id)}
              target="_blank"
              rel="noreferrer"
            >
              <img src={answerImageUrl(id)} alt="作答照片" />
              <span className={styles.thumbRole}>
                {roleLabel[attempt.image_roles[id]] ?? '我的作答'}
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

export function ReferenceAnalysis({ detail }: { detail: PracticeResponse }) {
  const question = detail.question
  const hasAnalysis =
    question &&
    (question.analysis_text ||
      question.analysis_image ||
      question.expected ||
      question.solution_note)
  if (hasAnalysis)
    return (
      <Fold title="参考解析" defaultOpen>
        {question.expected && (
          <p>
            <b>参考答案：</b>
            <MathText text={question.expected} />
          </p>
        )}
        {question.analysis_image && (
          <img className={styles.questionImage} src={question.analysis_image} alt="参考解析" />
        )}
        {question.analysis_text && <MathText text={question.analysis_text} />}
        {question.solution_note && (
          <p>
            <MathText text={question.solution_note} />
          </p>
        )}
      </Fold>
    )
  return null
}

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
  const [supplementing, setSupplementing] = useState(false)
  const { practice, latest_attempt: attempt } = detail
  const assessment = attempt?.assessment
  if (!attempt || !assessment) return null
  const correctness = assessmentCorrectness(assessment)
  const valid = (assessment.observations ?? []).filter((item) => item.status === 'valid')
  const nextIndex = group.items.findIndex((item) => item.status === 'pending')
  const next = nextIndex >= 0 ? group.items[nextIndex] : undefined
  const needsMaterial = assessment.needs_material ?? []
  const canSupplement = detail.actions.includes('supplement')

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
            <span className={styles.when}>{submittedTime(attempt.created_at)}</span>
          </div>
          {note && <p className={styles.stopped}>{note}</p>}
          <QuestionContent question={detail.question} />
          <SubmittedAttempt attempt={attempt} />
          {!note && (
            <div className={styles.gradedActions}>
              {canSupplement && !supplementing && (
                <Button size="sm" onClick={() => setSupplementing(true)}>
                  <Upload size={16} aria-hidden />
                  补充步骤或照片
                </Button>
              )}
              <ButtonLink size="sm" variant="ghost" to={practiceLink(practice.bank_id)}>
                单独再做一次
              </ButtonLink>
              {detail.actions.includes('reveal_analysis') && (
                <RevealButton
                  bankId={practice.bank_id}
                  kind="analysis"
                  label="查看参考解析"
                  variant="ghost"
                >
                  查看后会记下“看过解析”。之后的补充作答会和独立完成的作答分开统计。
                </RevealButton>
              )}
            </div>
          )}
          {supplementing && (
            <>
              <AttemptForm
                practiceId={practice.id}
                attemptId={attempt.id}
                showExposure={false}
                onSubmitted={() => setSupplementing(false)}
              />
              <Button size="sm" variant="ghost" onClick={() => setSupplementing(false)}>
                取消补充
              </Button>
            </>
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
            {needsMaterial.length > 0 && (
              <div className={styles.feedbackSection}>
                <h4>请补充这些内容</h4>
                <ul className={styles.needList}>
                  {needsMaterial.map((item, index) => (
                    <li key={index}>
                      <MathText text={item} />
                    </li>
                  ))}
                </ul>
              </div>
            )}
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
                  {next && next.id !== practice.id && (
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
            <ReferenceAnalysis detail={detail} />
          </div>
        </div>
      </div>
    </Card>
  )
}
