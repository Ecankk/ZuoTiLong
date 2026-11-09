import * as Dialog from '@radix-ui/react-dialog'
import { EyeOff, X } from 'lucide-react'
import { useLayoutEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { endpoints } from '../../api/endpoints'
import { useAction, useFreePractice } from '../../api/queries'
import type { BankCard, BankTopics, BookLocator } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Button, ButtonLink } from '../../components/ui/Button'
import { Chip } from '../../components/ui/Chip'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { cx } from '../../lib/cx'
import { friendlyError } from '../../lib/errors'
import { mathTypeName } from '../../lib/labels'
import { RevealButton } from '../practice/RevealButton'
import { TopicName } from '../topics/TopicName'
import styles from './BankPage.module.css'
import { ErrataNote } from './Errata'
import { QuestionText } from './QuestionText'

/** 示例题集只用于开发和测试，不出现在题库和考点页里 */
export const hiddenCollection = 'example'

export const practiceLink = (bankId: string) => `/bank/${encodeURIComponent(bankId)}/practice`

/** 打开整题时读一次做题接口，按它给的 actions 决定是否显示入口 */
function PracticeEntry({ bankId }: { bankId: string }) {
  const { data } = useFreePractice(bankId)
  if (!data?.actions.includes('submit')) return null
  return (
    <div className={styles.cardActions}>
      <ButtonLink variant="primary" to={practiceLink(bankId)}>
        做这道题
      </ButtonLink>
      {data.attempt_count > 0 && <span className={styles.count}>已做 {data.attempt_count} 次</span>}
    </div>
  )
}

export type BankTopic = BankTopics['items'][number]['topics'][number]

/** 教辅题的篇章，如“强化篇 · 第一章 函数极限”；不知道就是空字符串 */
export const bookSection = (book: BookLocator | undefined) =>
  [book?.part, book?.chapter].filter(Boolean).join(' · ')

/**
 * 教辅题的题号，如“第 3 题”。接口没给 number 时，从定位里的“#q3”推出来；都没有就是空字符串。
 */
export function bookNumber(book: BookLocator) {
  const number = book.number?.trim() || /#q(\d+)$/.exec(book.locator ?? '')?.[1] || ''
  return number ? (/^\d+$/.test(number) ? `第 ${number} 题` : number) : ''
}

/**
 * 题目标题：真题用“年份 类别 · 第N题”，教辅题用“篇章 · 原题号”。
 * 缺少的部分不显示，全都不知道时返回空字符串。
 */
export function bankTitle(card: Pick<BankCard, 'book' | 'year' | 'math_type' | 'number'>) {
  if (card.book) return [bookSection(card.book), bookNumber(card.book)].filter(Boolean).join(' · ')
  if (!card.year || !card.math_type || !card.number) return ''
  return `${card.year} ${mathTypeName(card.math_type)} · 第 ${card.number} 题`
}

/* 纯文字题用 question_text；旧图片题的 stem 只是“年份 类别 第N题 · 考点”的说明，有图时不当题干显示。 */

function Meta({ card, showType = true }: { card: BankCard; showType?: boolean }) {
  return (
    <div className={styles.meta}>
      {showType && card.question_type && <Chip>{card.question_type}</Chip>}
      {card.max_score !== null && <Chip>{card.max_score} 分</Chip>}
      {card.reserved && <Chip tone="unknown">留作整卷自测</Chip>}
      {Boolean(card.errata?.length) && <Chip tone="primary">本题已按勘误修正</Chip>}
    </div>
  )
}

export function TopicTags({ topics }: { topics: BankTopic[] }) {
  if (!topics.length) return null
  return (
    <div className={styles.tags}>
      {topics.map((topic) => (
        <Link key={topic.topic_id} to={`/topics/${encodeURIComponent(topic.topic_id)}`}>
          <Chip tone={topic.role === 'primary' ? 'primary' : 'plain'}>
            <TopicName name={topic.name} />
          </Chip>
        </Link>
      ))}
    </div>
  )
}

/** 不能直接看的题：显示原因；不是预留卷的可以确认后查看。 */
function Hidden({ card }: { card: BankCard }) {
  return (
    <div className={styles.hidden}>
      <EyeOff size={20} aria-hidden />
      <p>{card.reason || '这道题暂不显示。'}</p>
      {!card.reserved && (
        <RevealButton bankId={card.id} kind="question" label="查看题目">
          查看后会记下“看过这道题”。以后用这套真题整卷自测时，这道题的结果会单独标出。
        </RevealButton>
      )}
    </div>
  )
}

/** 列表卡片里题面最多露出的高度，和 .clamped 的 max-height 一致 */
const clampHeight = 220

/** 内容是否高过截断高度；公式字体、图片加载后高度会变，所以持续观察 */
function useTaller(limit: number) {
  const ref = useRef<HTMLDivElement>(null)
  const [taller, setTaller] = useState(false)
  useLayoutEffect(() => {
    const node = ref.current
    if (!node) return
    const check = () => setTaller(node.offsetHeight > limit + 4)
    check()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(check)
    observer.observe(node)
    return () => observer.disconnect()
  }, [limit])
  return [ref, taller] as const
}

function QuestionBody({ card, full }: { card: BankCard; full: boolean }) {
  // 有些题（如示例题）没有原题图片：图片读不到时改用文字说明
  const [imageFailed, setImageFailed] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [content, taller] = useTaller(clampHeight)
  if (!card.can_view) return <Hidden card={card} />
  const showImage = Boolean(card.question_image) && !imageFailed
  const text = card.question_text ?? (showImage ? null : card.stem)
  const clamped = !full && !expanded
  return (
    <div className={styles.body}>
      <div className={cx(clamped && styles.clamped, clamped && taller && styles.faded)}>
        <div ref={content}>
          {showImage && (
            <img
              className={styles.questionImage}
              src={card.question_image}
              alt={`${bankTitle(card) || '题目'}原题`}
              loading="lazy"
              onError={() => setImageFailed(true)}
            />
          )}
          {text && <QuestionText text={text} />}
        </div>
      </div>
      {!full && taller && (
        <button
          type="button"
          className={styles.expand}
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? '收起' : '展开全文'}
        </button>
      )}
    </div>
  )
}

/** 查看解析：先确认（会记录看过解析）；还没允许时先走 reveal。 */
function Analysis({ card }: { card: BankCard }) {
  const [confirm, setConfirm] = useState(false)
  const [shown, setShown] = useState(false)
  const reveal = useAction(() => endpoints.reveal(card.id, 'analysis'), [['bank']])
  const hasAnalysis = Boolean(card.analysis_image || card.analysis_text)
  if (!card.can_view) return null
  if (!hasAnalysis)
    return (
      <>
        <p className={styles.note}>这道题暂时没有解析。</p>
        <ErrataNote errata={card.errata} answerVisible={false} />
      </>
    )
  if (shown)
    return (
      <section className={styles.analysis}>
        <h3>参考解析</h3>
        <ErrataNote errata={card.errata} answerVisible />
        {card.analysis_image && (
          <img className={styles.questionImage} src={card.analysis_image} alt="参考解析" />
        )}
        {card.analysis_text && (
          <div className="read">
            <MathText text={card.analysis_text} />
          </div>
        )}
      </section>
    )
  const open = () => {
    if (card.analysis_allowed) {
      setShown(true)
      setConfirm(false)
    } else
      reveal.mutate(undefined, {
        onSuccess: () => {
          setShown(true)
          setConfirm(false)
        },
      })
  }
  return (
    <>
      <ErrataNote errata={card.errata} answerVisible={false} />
      <Button onClick={() => setConfirm(true)}>查看解析</Button>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="查看参考解析？"
        confirmLabel="确认查看解析"
        pending={reveal.isPending}
        error={reveal.error ? friendlyError(reveal.error) : undefined}
        onConfirm={open}
      >
        查看后会记下“看过这道题的解析”。如果以后在练习里遇到这道题，独立作答的结果会单独统计。
      </ConfirmDialog>
    </>
  )
}

/**
 * 题库列表里的一张题卡。inSection：教辅题已经按篇章分组，标题只写“第 N 题 · 题型”，不重复篇章。
 */
export function BankQuestionCard({
  card,
  topics,
  onOpen,
  inSection = false,
}: {
  card: BankCard
  topics: BankTopic[]
  onOpen: () => void
  inSection?: boolean
}) {
  const title =
    inSection && card.book
      ? [bookNumber(card.book), card.question_type].filter(Boolean).join(' · ')
      : bankTitle(card)
  return (
    <article className={styles.card}>
      <header className={styles.cardHead}>
        {title && <h3>{title}</h3>}
        <Meta card={card} showType={!(inSection && card.book)} />
      </header>
      <QuestionBody card={card} full={false} />
      <TopicTags topics={topics} />
      <div className={styles.cardActions}>
        {/* 列表里只按题卡状态粗筛；能否提交以做题页读到的 actions 为准 */}
        {card.can_view && !card.reserved && (
          <ButtonLink size="sm" variant="primary" to={practiceLink(card.id)}>
            做这道题
          </ButtonLink>
        )}
        <Button size="sm" onClick={onOpen}>
          查看整题
        </Button>
      </div>
    </article>
  )
}

export function BankQuestionDialog({
  card,
  topics,
  onClose,
}: {
  card: BankCard
  topics: BankTopic[]
  onClose: () => void
}) {
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.dialog} aria-describedby={undefined}>
          <header className={styles.dialogHead}>
            <Dialog.Title>{bankTitle(card) || '题目'}</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className={styles.close} aria-label="关闭">
                <X size={18} aria-hidden />
              </button>
            </Dialog.Close>
          </header>
          <Meta card={card} />
          <QuestionBody card={card} full />
          <TopicTags topics={topics} />
          {card.can_view && !card.reserved && <PracticeEntry bankId={card.id} />}
          <Analysis card={card} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
