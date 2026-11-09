import { EyeOff } from 'lucide-react'
import type { PracticeResponse } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Card } from '../../components/ui/Card'
import { cx } from '../../lib/cx'
import { mathTypeName } from '../../lib/labels'
import { AttemptForm } from './AttemptForm'
import { PracticeHeading } from './PracticeHeading'
import { RevealButton } from './RevealButton'
import { splitQuestionText } from './selection'
import styles from './PracticeCard.module.css'

/**
 * 练习题面：图片题显示原题图，纯文字题按公式排版。
 * 有原题图时，“2022 数学三 第22题 · 参数估计”这样的说明文字不当题干显示（章节由标题显示）。
 */
export function QuestionContent({
  question,
}: {
  question: { question_text?: string | null; question_image?: string | null } | null
}) {
  if (!question) return null
  const { text } = splitQuestionText(question)
  return (
    <>
      {question.question_image && (
        <img className={styles.questionImage} src={question.question_image} alt="练习原题" />
      )}
      {text && (
        <div className={cx('read', styles.question)}>
          <MathText text={text} />
        </div>
      )}
    </>
  )
}

function MaskedQuestion({ detail }: { detail: PracticeResponse }) {
  const type = detail.practice.access.math_type
  const mathType = type ? mathTypeName(type) : ''
  const canReveal = detail.actions.includes('reveal_question')
  return (
    <div className={styles.masked}>
      <EyeOff size={22} aria-hidden />
      <strong>{mathType ? `${mathType}真题，默认遮挡` : '这道题默认遮挡'}</strong>
      <p>
        {canReveal
          ? `你在备考${mathType}，同类别真题可能留作整卷自测。查看后会记为“看过题目”。`
          : '这道题已留作整卷自测，暂不显示。'}
      </p>
      {canReveal && (
        <RevealButton
          bankId={detail.practice.bank_id}
          kind="question"
          label="查看题目"
          variant="primary"
        >
          查看后会记下“看过这道题”。以后用这套真题整卷自测时，这道题的结果会单独标出。
        </RevealButton>
      )}
    </div>
  )
}

/** 还没作答的练习：看题、作答、提交。 */
export function AnswerCard({ detail, eyebrow }: { detail: PracticeResponse; eyebrow: string }) {
  const { practice } = detail
  const canSubmit = detail.actions.includes('submit')
  return (
    <Card className={styles.card} aria-label="当前练习">
      <div className={styles.split}>
        <div>
          <PracticeHeading detail={detail} eyebrow={eyebrow} />
          {detail.selection_reason && (
            <p className={styles.why}>
              <b>为什么练这道：</b>
              <MathText text={detail.selection_reason} />
            </p>
          )}
          {detail.question ? (
            <QuestionContent question={detail.question} />
          ) : (
            <MaskedQuestion detail={detail} />
          )}
        </div>
        {canSubmit ? (
          <AttemptForm practiceId={practice.id} showExposure />
        ) : (
          <p className={cx(styles.answer, styles.note)}>看过题目后就可以作答。</p>
        )}
      </div>
    </Card>
  )
}
