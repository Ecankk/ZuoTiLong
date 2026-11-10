import { useState } from 'react'
import { useFreeAttempts } from '../../api/queries'
import type { FreeAttempt, FreeReference } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Button } from '../../components/ui/Button'
import { Chip, CorrectnessChip } from '../../components/ui/Chip'
import { ErrorState } from '../../components/ui/ErrorState'
import { Fold } from '../../components/ui/Fold'
import { Skeleton } from '../../components/ui/Skeleton'
import { assessmentCorrectness } from '../../lib/labels'
import { QuestionContent } from '../practice/AnswerCard'
import { ErrataNote } from './Errata'
import styles from './FreePracticePage.module.css'

const pageSize = 10

function when(iso: string) {
  const date = new Date(iso)
  const time = date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  return new Date().toDateString() === date.toDateString()
    ? `今天 ${time}`
    : `${date.getMonth() + 1}月${date.getDate()}日 ${time}`
}

const duration = (seconds: number | null) =>
  seconds == null
    ? ''
    : seconds < 60
      ? `用时 ${Math.round(seconds)} 秒`
      : `用时 ${Math.round(seconds / 60)} 分钟`

/** 参考答案和解析（文字或图片） */
export function ReferenceBlock({
  reference,
  open = false,
}: {
  reference: FreeReference
  open?: boolean
}) {
  const parts: [string, string | null | undefined, string | null | undefined][] = [
    ['参考答案', reference.answer_text, reference.answer_image],
    ['解析', reference.analysis_text, reference.analysis_image],
  ]
  if (!parts.some(([, text, image]) => text || image)) return null
  return (
    <Fold title="参考答案与解析" defaultOpen={open}>
      <ErrataNote errata={reference.errata} answerVisible />
      {parts.map(([label, text, image]) =>
        text || image ? (
          <div key={label} className={styles.reference}>
            <h4>{label}</h4>
            {image && <img src={image} alt={label} className={styles.referenceImage} />}
            {text && (
              <div className="read">
                <MathText text={text} />
              </div>
            )}
          </div>
        ) : null,
      )}
    </Fold>
  )
}

/** 一次作答：结果、作答内容、批改反馈和这次的参考快照。 */
export function FreeAttemptView({
  attempt,
  referenceOpen = false,
}: {
  attempt: FreeAttempt
  referenceOpen?: boolean
}) {
  const assessment = attempt.assessment
  const answer = attempt.choice || attempt.response
  return (
    <div className={styles.attempt}>
      <div className={styles.meta}>
        {assessment ? (
          <CorrectnessChip value={assessmentCorrectness(assessment)} />
        ) : (
          <Chip tone="unknown">{attempt.job ? '正在批改' : '待批改'}</Chip>
        )}
        {attempt.answer_exposed && <Chip tone="partial">受提示完成</Chip>}
        <span className={styles.muted}>
          {[when(attempt.created_at), duration(attempt.elapsed_seconds)]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </div>
      {(answer || attempt.image_ids.length > 0) && (
        <p className={styles.response}>
          <span className={styles.muted}>你的作答：</span>
          {answer && <MathText text={answer} />}
          {attempt.image_ids.length > 0 && (
            <span className={styles.muted}> （附 {attempt.image_ids.length} 张照片）</span>
          )}
        </p>
      )}
      {assessment && (
        <div className="read">
          {assessment.feedback && (
            <p>
              <MathText text={assessment.feedback} />
            </p>
          )}
          {assessment.first_error && (
            <p>
              <strong>首个错误：</strong>
              <MathText text={assessment.first_error.step} />
            </p>
          )}
          {assessment.next_step && (
            <p>
              <strong>下一步：</strong>
              <MathText text={assessment.next_step} />
            </p>
          )}
        </div>
      )}
      {attempt.materials.reference && (
        <ReferenceBlock reference={attempt.materials.reference} open={referenceOpen} />
      )}
    </div>
  )
}

/** 历史作答：分页，每条用它自己的题面和参考快照。 */
export function FreeHistory({ bankId, total }: { bankId: string; total: number }) {
  const [page, setPage] = useState(0)
  const { data, isPending, isError, error, refetch } = useFreeAttempts(
    bankId,
    page * pageSize,
    pageSize,
  )
  const pages = Math.max(1, Math.ceil((data?.total ?? total) / pageSize))
  return (
    <section className={styles.card} aria-label="历史作答">
      <h2 className={styles.historyTitle}>历史作答 · 共 {data?.total ?? total} 次</h2>
      {isPending && <Skeleton variant="rows" rows={3} />}
      {isError && !data && (
        <ErrorState error={error} title="历史作答没有读出来" onRetry={() => void refetch()} />
      )}
      <ol className={styles.history}>
        {data?.items.map((attempt, index) => (
          <li key={attempt.id}>
            <span className={styles.ordinal}>
              第 {(data.total ?? total) - page * pageSize - index} 次
            </span>
            <FreeAttemptView attempt={attempt} />
            <Fold title="当时的题面">
              <QuestionContent question={attempt.materials.question} />
            </Fold>
          </li>
        ))}
      </ol>
      {pages > 1 && (
        <nav className={styles.pager} aria-label="历史分页">
          <Button size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
            上一页
          </Button>
          <span>
            第 {page + 1} / {pages} 页
          </span>
          <Button size="sm" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
            下一页
          </Button>
        </nav>
      )}
    </section>
  )
}
