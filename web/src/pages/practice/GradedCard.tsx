import { ArrowRight, Check, Upload } from 'lucide-react'
import { useState } from 'react'
import type { Attempt, PracticeResponse } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Button, ButtonLink } from '../../components/ui/Button'
import { practiceLink } from '../bank/BankQuestion'
import { Card } from '../../components/ui/Card'
import { CorrectnessChip } from '../../components/ui/Chip'
import { Fold } from '../../components/ui/Fold'
import { cx } from '../../lib/cx'
import { assessmentCorrectness } from '../../lib/labels'
import { QuestionContent } from './AnswerCard'
import { AttemptForm } from './AttemptForm'
import { PracticeHeading } from './PracticeHeading'
import { RevealButton } from './RevealButton'
import { usefulAnalysis } from './selection'
import styles from './PracticeCard.module.css'

/** 作答照片沿用旧的图片入口 */
export const answerImageUrl = (id: string) => `/api/answer-images/${encodeURIComponent(id)}`

/** 下一道要做的题，由练习页按当前列表算好传进来 */
export type NextPractice = { to: string; label: string }

const roleLabel: Record<string, string> = {
  own_work: '我的作答',
  marking: '事后批改',
  external_solution: '参考解析',
}

export function submittedTime(iso: string) {
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

/** 反馈原文按换行分段显示（不改动文字内容） */
const paragraphs = (text: string) =>
  text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)

/** 参考材料里真正有内容的部分；“参考解析见原图”这类占位文字不算 */
function referenceParts(detail: PracticeResponse) {
  const question = detail.question
  if (!question) return null
  const parts = {
    expected: question.expected || null,
    image: question.analysis_image || null,
    text: usefulAnalysis(question.analysis_text),
    note: question.solution_note || null,
  }
  return Object.values(parts).some(Boolean) ? parts : null
}

export function ReferenceAnalysis({
  detail,
  defaultOpen = false,
}: {
  detail: PracticeResponse
  defaultOpen?: boolean
}) {
  const parts = referenceParts(detail)
  if (!parts) return null
  return (
    <Fold title="参考解析" hint="参考答案和完整解析" defaultOpen={defaultOpen}>
      {parts.expected && (
        <p>
          <b>参考答案：</b>
          <MathText text={parts.expected} />
        </p>
      )}
      {parts.image && <img className={styles.questionImage} src={parts.image} alt="参考解析" />}
      {parts.text && <MathText text={parts.text} />}
      {parts.note && (
        <p>
          <MathText text={parts.note} />
        </p>
      )}
    </Fold>
  )
}

/**
 * 已批改的练习。结论、问题与首错、建议一直显示；
 * 做对的部分、参考思路、参考解析默认收起，需要时再展开，和题目页的分层保持一致。
 */
export function GradedCard({
  detail,
  eyebrow,
  next,
  note,
}: {
  detail: PracticeResponse
  eyebrow: string
  next?: NextPractice
  /** 练习已停用时的说明 */
  note?: string
}) {
  const [supplementing, setSupplementing] = useState(false)
  const { practice, latest_attempt: attempt } = detail
  const assessment = attempt?.assessment
  if (!attempt || !assessment) return null
  const correctness = assessmentCorrectness(assessment)
  const valid = (assessment.observations ?? []).filter((item) => item.status === 'valid')
  const problems = (assessment.observations ?? []).filter(
    (item) => item.status !== 'valid' && item.step !== assessment.first_error?.step,
  )
  const causes = assessment.possible_causes ?? []
  const needsMaterial = assessment.needs_material ?? []
  const canSupplement = detail.actions.includes('supplement')
  const [lead, ...rest] = paragraphs(assessment.feedback)
  const hasProblems = Boolean(assessment.first_error || problems.length > 0 || causes.length > 0)
  const hasFolds = valid.length > 0 || assessment.reference_reasoning || referenceParts(detail)

  return (
    <Card className={styles.card} aria-label="已批改的练习">
      <PracticeHeading detail={detail} eyebrow={eyebrow}>
        <CorrectnessChip value={correctness} />
        <span className={styles.when}>{submittedTime(attempt.created_at)}</span>
      </PracticeHeading>
      <div className={styles.split}>
        <div>
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
            <section className={styles.feedbackSection} aria-label="结论">
              <h4>结论</h4>
              {lead && (
                <p>
                  <MathText text={lead} />
                </p>
              )}
              {rest.length > 0 && (
                <Fold title="完整结论" hint={`还有 ${rest.length} 段`}>
                  {rest.map((text, index) => (
                    <p key={index}>
                      <MathText text={text} />
                    </p>
                  ))}
                </Fold>
              )}
            </section>
            {hasProblems && (
              <section className={styles.feedbackSection} aria-label="问题与首错">
                <h4>问题与首错</h4>
                {assessment.first_error && (
                  <div className={styles.firstError}>
                    <b>首个错误：</b>
                    <MathText text={assessment.first_error.step} />
                    {assessment.first_error.evidence && (
                      <small>
                        <MathText text={assessment.first_error.evidence} />
                      </small>
                    )}
                  </div>
                )}
                {problems.length > 0 && (
                  <ul className={styles.problemList}>
                    {problems.map((item, index) => (
                      <li key={index}>
                        <MathText text={item.step} />
                        {item.evidence && (
                          <small>
                            <MathText text={item.evidence} />
                          </small>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                {causes.length > 0 && (
                  <Fold title="可能的原因" hint={`${causes.length} 条`}>
                    <ul className={styles.problemList}>
                      {causes.map((cause) => (
                        <li key={cause.id}>
                          <MathText text={cause.label} />
                          {cause.correction && (
                            <small>
                              改进：
                              <MathText text={cause.correction} />
                            </small>
                          )}
                        </li>
                      ))}
                    </ul>
                  </Fold>
                )}
              </section>
            )}
            {(assessment.next_step || needsMaterial.length > 0 || next) && (
              <section className={styles.feedbackSection} aria-label="建议">
                <h4>建议</h4>
                {needsMaterial.length > 0 && (
                  <>
                    <p>请补充这些内容：</p>
                    <ul className={styles.needList}>
                      {needsMaterial.map((item, index) => (
                        <li key={index}>
                          <MathText text={item} />
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                {(assessment.next_step || next) && (
                  <div className={styles.nextStep}>
                    <span>
                      {assessment.next_step ? (
                        <MathText text={assessment.next_step} />
                      ) : (
                        '接着做下一道。'
                      )}
                    </span>
                    {next && (
                      <ButtonLink size="sm" variant="soft" to={next.to} title={next.label}>
                        做下一道
                        <ArrowRight size={14} aria-hidden />
                      </ButtonLink>
                    )}
                  </div>
                )}
              </section>
            )}
            {hasFolds && (
              <div className={styles.feedbackFolds}>
                {valid.length > 0 && (
                  <Fold title="做对的部分" hint={`${valid.length} 步`}>
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
                  </Fold>
                )}
                {assessment.reference_reasoning && (
                  <Fold title="参考思路">
                    <p>
                      <MathText text={assessment.reference_reasoning} />
                    </p>
                  </Fold>
                )}
                <ReferenceAnalysis detail={detail} />
              </div>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}
