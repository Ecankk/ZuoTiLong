import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Clock, Eye, EyeOff, Lock } from 'lucide-react'
import { useEffect, useState, type ClipboardEvent } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { endpoints, requestId } from '../../api/endpoints'
import { useAction, useBankCollections, useFreePractice, useTasks } from '../../api/queries'
import type { FreeAttemptBody, FreePractice } from '../../api/types'
import { Button, ButtonLink } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip } from '../../components/ui/Chip'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { PageHeader } from '../../components/ui/PageHeader'
import { choiceLetters } from '../../lib/choices'
import { cx } from '../../lib/cx'
import { QuestionContent } from '../practice/AnswerCard'
import { PhotoPicker, usePhotoUpload, type Photo } from '../practice/PhotoPicker'
import practiceStyles from '../practice/PracticeCard.module.css'
import { RevealButton } from '../practice/RevealButton'
import { bankTitle } from './BankQuestion'
import { FreeAttemptView, FreeHistory, ReferenceBlock } from './FreeAttempt'
import styles from './FreePracticePage.module.css'
import { friendlyError } from '../../lib/errors'
import { clientStateKeys, useClientState } from '../../lib/clientState'
import { Skeleton } from '../../components/ui/Skeleton'

type Draft = { text: string; choice: string; photos: Photo[] }
const emptyDraft: Draft = { text: '', choice: '', photos: [] }
const draftKey = (bankId: string) => `free-practice:${bankId}`

/** 作答内容（不含 request_id 和耗时），用来判断重试时内容有没有改过 */
const contentOf = (body: Omit<FreeAttemptBody, 'request_id' | 'elapsed_seconds'>) =>
  JSON.stringify([
    body.response,
    body.choice ?? '',
    body.image_ids,
    body.image_roles,
    body.answer_exposed,
  ])

function useElapsed() {
  const [start, setStart] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const seconds = Math.max(0, Math.round((now - start) / 1000))
  return { seconds, restart: () => setStart(Date.now()) }
}

const clock = (seconds: number) =>
  `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`

/** 用时默认不显示，免得一进来就有压力；想看时点一下，记住这个选择。计时本身一直在走，提交时照常记录。 */
function useShowTimer() {
  const state = useClientState<boolean>(clientStateKeys.freePracticeTimer, {
    fallback: false,
    fromLegacy: (raw) => (raw === '1' ? true : raw === '0' ? false : undefined),
  })
  return { show: state.value, toggle: () => state.set(!state.value) }
}

/** 作答区：选择题字母按钮，填空题一个输入框，解答题文字加照片。草稿用独立 key 自动保存。 */
function AnswerForm({ detail, initial }: { detail: FreePractice; initial: Draft }) {
  const client = useQueryClient()
  const { bank_id: bankId } = detail
  const type = detail.question_type ?? detail.source.question_type ?? ''
  const isChoice = type === '选择题'
  const isBlank = type === '填空题'
  const [text, setText] = useState(initial.text)
  const [choice, setChoice] = useState(initial.choice)
  const [photos, setPhotos] = useState<Photo[]>(initial.photos)
  const [exposed, setExposed] = useState(false)
  const [revealing, setRevealing] = useState(false)
  // 已发出但还没成功的作答：内容不变时重试沿用同一个 request_id 和同一份请求
  const [pending, setPending] = useState<FreeAttemptBody | null>(null)
  const elapsed = useElapsed()
  const timer = useShowTimer()
  const { add, uploading, error: uploadError } = usePhotoUpload(photos, setPhotos)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void endpoints.saveDraft(draftKey(bankId), { text, choice, photos }).catch(() => undefined)
    }, 800)
    return () => window.clearTimeout(timer)
  }, [bankId, text, choice, photos])

  const reveal = useAction(() => endpoints.reveal(bankId, 'analysis'), [['bank', bankId]])
  const submit = useAction(
    (body: FreeAttemptBody) => endpoints.submitFreeAttempt(bankId, body),
    [['bank', bankId], ['tasks'], ['profile'], ['knowledge']],
  )

  const content = {
    response: isChoice ? choice : text.trim(),
    ...(isChoice ? { choice } : {}),
    // 只有选择题不收照片；填空和解答都可以附手写照片
    image_ids: isChoice ? [] : photos.map((photo) => photo.id),
    image_roles: isChoice ? {} : Object.fromEntries(photos.map((photo) => [photo.id, photo.role])),
    answer_exposed: exposed,
  }
  const empty = isChoice ? !choice : !content.response && content.image_ids.length === 0
  const send = () => {
    const body =
      pending && contentOf(pending) === contentOf(content)
        ? pending
        : { ...content, request_id: requestId(), elapsed_seconds: elapsed.seconds }
    setPending(body)
    submit.mutate(body, {
      onSuccess: () => {
        setPending(null)
        setText('')
        setChoice('')
        setPhotos(() => [])
        setExposed(false)
        elapsed.restart()
        void endpoints.saveDraft(draftKey(bankId), null).catch(() => undefined)
        void client.invalidateQueries({ queryKey: ['draft', bankId] })
      },
    })
  }
  const onPaste = (event: ClipboardEvent) => {
    const files = Array.from(event.clipboardData.files)
    if (files.length) {
      event.preventDefault()
      add(files)
    }
  }
  const error = uploadError ?? (submit.error && friendlyError(submit.error))

  return (
    <Card padded className={styles.card} aria-label="作答">
      <div className={styles.answerHead}>
        <h2>你的作答</h2>
        <button
          type="button"
          className={styles.timer}
          aria-pressed={timer.show}
          title={timer.show ? '隐藏用时' : '显示用时'}
          onClick={timer.toggle}
        >
          <Clock size={14} aria-hidden />
          {timer.show ? <span aria-label="已用时间">{clock(elapsed.seconds)}</span> : '显示用时'}
        </button>
      </div>
      {isChoice ? (
        <div className={styles.choices} role="radiogroup" aria-label="选项">
          {choiceLetters(detail.question.question_text).map((letter) => (
            <button
              key={letter}
              type="button"
              role="radio"
              aria-checked={choice === letter}
              className={cx(styles.choice, choice === letter && styles.chosen)}
              onClick={() => setChoice(letter)}
            >
              {letter}
            </button>
          ))}
        </div>
      ) : isBlank ? (
        <>
          <input
            className={styles.blank}
            aria-label="填空答案"
            placeholder="填写答案，如 1/2 或 \frac{1}{2}"
            maxLength={2000}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onPaste={onPaste}
          />
          <p className={styles.blankHint}>不好打字时可以直接上传手写照片</p>
          <PhotoPicker photos={photos} setPhotos={setPhotos} add={add} uploading={uploading} />
        </>
      ) : (
        <>
          <textarea
            className={practiceStyles.textarea}
            aria-label="解答过程"
            placeholder="写下关键步骤即可；也可以直接上传手写照片，不用把整页誊一遍。"
            maxLength={16000}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onPaste={onPaste}
          />
          <PhotoPicker photos={photos} setPhotos={setPhotos} add={add} uploading={uploading} />
        </>
      )}

      {exposed && (
        <p className={styles.assisted} role="status">
          你已经看过答案和解析，这次作答算“受提示完成”，不算独立完成。
        </p>
      )}
      {exposed && detail.reference && <ReferenceBlock reference={detail.reference} open />}
      {error && <p className={practiceStyles.formError}>{error}</p>}

      <div className={styles.submitRow}>
        {!exposed && detail.actions.includes('reveal_analysis') && (
          <Button variant="ghost" onClick={() => setRevealing(true)}>
            <Eye size={16} aria-hidden />
            看答案/解析
          </Button>
        )}
        <span className={practiceStyles.submitHint}>
          {isChoice
            ? '提交后立即判对错'
            : isBlank
              ? '和参考答案一致会立即判对；写法不同时交给做题龙判断'
              : '提交后由做题龙批改'}
        </span>
        <Button
          variant="primary"
          size="lg"
          disabled={empty || submit.isPending || uploading}
          onClick={send}
        >
          {submit.isPending ? '正在提交…' : pending && submit.isError ? '重新提交' : '提交'}
        </Button>
      </div>

      <ConfirmDialog
        open={revealing}
        onOpenChange={setRevealing}
        title="先看答案和解析？"
        confirmLabel="确认查看"
        pending={reveal.isPending}
        error={reveal.error ? friendlyError(reveal.error) : undefined}
        onConfirm={() =>
          reveal.mutate(undefined, {
            onSuccess: () => {
              setExposed(true)
              setRevealing(false)
            },
          })
        }
      >
        看过之后，这次作答算“受提示完成”，在画像里和独立做对分开统计。
      </ConfirmDialog>
    </Card>
  )
}

/** 草稿读回来后再显示作答区，保证初始内容一次到位 */
function AnswerArea({ detail }: { detail: FreePractice }) {
  const { data, isPending } = useQuery({
    queryKey: ['draft', detail.bank_id],
    queryFn: () => endpoints.draft<Draft>(draftKey(detail.bank_id)).catch(() => null),
    staleTime: Infinity,
  })
  if (isPending) return <Skeleton rows={4} />
  return <AnswerForm key={detail.bank_id} detail={detail} initial={{ ...emptyDraft, ...data }} />
}

type BlockReason = 'masked' | 'reserved' | 'unknown'

/**
 * 403 的原因。后端之后会给结构化的 reason（masked / reserved）；
 * 现在只有一句“题目未允许查看或属于预留卷”，分不清时按 unknown 两种都说明。
 */
function blockReason(error: Error): BlockReason {
  const reason = (error as Error & { reason?: unknown }).reason
  if (reason === 'masked' || reason === 'reserved') return reason
  return 'unknown'
}

/** 不能单独练的题：遮挡的题可以确认查看后再做；留作整卷自测的题说明原因。不留死路。 */
function Blocked({
  error,
  bankId,
  onRevealed,
}: {
  error: Error
  bankId: string
  onRevealed: () => void
}) {
  const forbidden = error instanceof ApiError && error.status === 403
  if (!forbidden)
    return (
      <Card padded className={styles.card}>
        <h2>没有打开这道题</h2>
        <p className={styles.muted}>{friendlyError(error)}</p>
        <div className={styles.blockedActions}>
          <ButtonLink to="/bank">回到题库</ButtonLink>
        </div>
      </Card>
    )
  const reason = blockReason(error)
  const reveal = (
    <RevealButton
      bankId={bankId}
      kind="question"
      label="确认查看后再做"
      variant="primary"
      onRevealed={onRevealed}
    >
      查看后会记下“看过这道题”。以后用这套真题整卷自测时，这道题的结果会单独标出。
    </RevealButton>
  )
  return (
    <Card padded className={styles.card}>
      <h2>这道题现在不能单独练习</h2>
      {reason === 'masked' && (
        <>
          <p className={styles.muted}>
            这是你备考类别的真题，默认遮挡，免得提前看到。确认查看后就可以在这里做。
          </p>
          <div className={styles.blockedActions}>
            {reveal}
            <ButtonLink variant="ghost" to="/bank">
              回到题库
            </ButtonLink>
          </div>
        </>
      )}
      {reason === 'reserved' && (
        <>
          <p className={styles.muted}>
            这套卷你留作整卷自测，单独练会提前看到题目，所以这里不显示。等整卷自测时再做。
          </p>
          <div className={styles.blockedActions}>
            <ButtonLink to="/bank">回到题库</ButtonLink>
          </div>
        </>
      )}
      {reason === 'unknown' && (
        <ul className={styles.reasons}>
          <li>
            <EyeOff size={18} aria-hidden />
            <div>
              <strong>如果是默认遮挡的同类别真题</strong>
              <p className={styles.muted}>确认查看后就可以在这里做。</p>
              {reveal}
            </div>
          </li>
          <li>
            <Lock size={18} aria-hidden />
            <div>
              <strong>如果这套卷你留作整卷自测</strong>
              <p className={styles.muted}>
                单独练会提前看到题目，所以这里不显示，等整卷自测时再做。
              </p>
              <ButtonLink variant="ghost" size="sm" to="/bank">
                回到题库
              </ButtonLink>
            </div>
          </li>
        </ul>
      )}
    </Card>
  )
}

/** 题库题目的独立做题页：/bank/:bankId/practice */
export function FreePracticePage() {
  const { bankId = '' } = useParams()
  const client = useQueryClient()
  const { data, error, isPending, refetch } = useFreePractice(bankId)
  const { data: collections } = useBankCollections()
  const { data: tasks } = useTasks()
  const latest = data?.latest_attempt
  const grading = Boolean(latest && !latest.assessment && latest.job)

  // 等待 AI 批改：任务状态有变化就重新读取这道题和历史
  useEffect(() => {
    if (grading) void client.invalidateQueries({ queryKey: ['bank', bankId, 'practice'] })
  }, [grading, tasks, client, bankId])

  const collection = collections?.find((c) => c.id === data?.collection_id)
  const title = data
    ? bankTitle({
        book: data.source.book,
        year: data.source.year ?? '',
        math_type: data.source.math_type ?? 0,
        number: data.source.number ?? 0,
      })
    : ''
  const type = data?.question_type ?? data?.source.question_type

  return (
    <>
      <Link to="/bank" className={styles.back}>
        <ArrowLeft size={14} aria-hidden /> 题库
      </Link>
      <PageHeader
        title="做这道题"
        subtitle={[collection?.name, title].filter(Boolean).join(' · ') || undefined}
      />
      {isPending && <Skeleton variant="question" />}
      {error && !data && (
        <Blocked error={error} bankId={bankId} onRevealed={() => void refetch()} />
      )}
      {data && (
        <div className={styles.column}>
          <Card padded className={styles.card} aria-label="题目">
            <div className={styles.meta}>
              {type && <Chip>{type}</Chip>}
              {data.source.max_score != null && <Chip>{data.source.max_score} 分</Chip>}
              {data.attempt_count > 0 && <Chip tone="unknown">已做 {data.attempt_count} 次</Chip>}
            </div>
            <QuestionContent question={data.question} />
          </Card>

          {latest && (
            <Card padded className={styles.card} aria-label="最近一次作答">
              <h2>最近一次作答</h2>
              {grading ? (
                <p className={styles.grading} role="status">
                  <span className={styles.spinner} aria-hidden />
                  正在批改，完成后这里会自动更新。可以先离开这个页面。
                </p>
              ) : (
                <FreeAttemptView attempt={latest} referenceOpen />
              )}
            </Card>
          )}

          {data.actions.includes('submit') ? (
            <AnswerArea detail={data} />
          ) : (
            <Card padded className={styles.muted}>
              这道题现在不能提交新的作答，可以查看以前的记录。
            </Card>
          )}

          {data.attempt_count > 0 && <FreeHistory bankId={bankId} total={data.attempt_count} />}
        </div>
      )}
    </>
  )
}
