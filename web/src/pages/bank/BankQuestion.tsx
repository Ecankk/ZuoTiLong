import * as Dialog from '@radix-ui/react-dialog'
import { EyeOff, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { endpoints } from '../../api/endpoints'
import { useAction, useFreePractice } from '../../api/queries'
import type { BankCard, BankTopics, BookLocator } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Button, ButtonLink } from '../../components/ui/Button'
import { Chip } from '../../components/ui/Chip'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { cx } from '../../lib/cx'
import { mathTypeName } from '../../lib/labels'
import { RevealButton } from '../practice/RevealButton'
import styles from './BankPage.module.css'

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
 * 题目标题：真题用“年份 类别 · 第N题”，教辅题用“篇章 · 原题号”。
 * 缺少的部分不显示，全都不知道时返回空字符串。
 */
export function bankTitle(card: Pick<BankCard, 'book' | 'year' | 'math_type' | 'number'>) {
  if (card.book) {
    const number = card.book.number?.trim()
    const label = number ? (/^\d+$/.test(number) ? `第 ${number} 题` : number) : ''
    return [bookSection(card.book), label].filter(Boolean).join(' · ')
  }
  if (!card.year || !card.math_type || !card.number) return ''
  return `${card.year} ${mathTypeName(card.math_type)} · 第 ${card.number} 题`
}

/* 纯文字题用 question_text；旧图片题的 stem 只是“年份 类别 第N题 · 考点”的说明，有图时不当题干显示。 */

function Meta({ card }: { card: BankCard }) {
  return (
    <div className={styles.meta}>
      {card.question_type && <Chip>{card.question_type}</Chip>}
      {card.max_score !== null && <Chip>{card.max_score} 分</Chip>}
      {card.reserved && <Chip tone="unknown">留作整卷自测</Chip>}
    </div>
  )
}

export function TopicTags({ topics }: { topics: BankTopic[] }) {
  if (!topics.length) return null
  return (
    <div className={styles.tags}>
      {topics.map((topic) => (
        <Link key={topic.topic_id} to={`/topics/${encodeURIComponent(topic.topic_id)}`}>
          <Chip tone={topic.role === 'primary' ? 'primary' : 'plain'}>{topic.name}</Chip>
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

function QuestionBody({ card, full }: { card: BankCard; full: boolean }) {
  // 有些题（如示例题）没有原题图片：图片读不到时改用文字说明
  const [imageFailed, setImageFailed] = useState(false)
  if (!card.can_view) return <Hidden card={card} />
  const showImage = Boolean(card.question_image) && !imageFailed
  const text = card.question_text ?? (showImage ? null : card.stem)
  return (
    <div className={cx(styles.body, !full && styles.clamped)}>
      {showImage && (
        <img
          className={styles.questionImage}
          src={card.question_image}
          alt={`${bankTitle(card) || '题目'}原题`}
          loading="lazy"
          onError={() => setImageFailed(true)}
        />
      )}
      {text && (
        <div className="read">
          <MathText text={text} />
        </div>
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
  if (!hasAnalysis) return <p className={styles.note}>这道题暂时没有解析。</p>
  if (shown)
    return (
      <section className={styles.analysis}>
        <h3>参考解析</h3>
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
      <Button onClick={() => setConfirm(true)}>查看解析</Button>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="查看参考解析？"
        confirmLabel="确认查看解析"
        pending={reveal.isPending}
        error={reveal.error?.message}
        onConfirm={open}
      >
        查看后会记下“看过这道题的解析”。如果以后在练习里遇到这道题，独立作答的结果会单独统计。
      </ConfirmDialog>
    </>
  )
}

export function BankQuestionCard({
  card,
  topics,
  onOpen,
}: {
  card: BankCard
  topics: BankTopic[]
  onOpen: () => void
}) {
  return (
    <article className={styles.card}>
      <header className={styles.cardHead}>
        {bankTitle(card) && <h3>{bankTitle(card)}</h3>}
        <Meta card={card} />
      </header>
      <QuestionBody card={card} full={false} />
      <TopicTags topics={topics} />
      <div className={styles.cardActions}>
        <Button size="sm" onClick={onOpen}>
          查看整题
        </Button>
        {/* 列表里只按题卡状态粗筛；能否提交以做题页读到的 actions 为准 */}
        {card.can_view && !card.reserved && (
          <ButtonLink size="sm" variant="soft" to={practiceLink(card.id)}>
            做这道题
          </ButtonLink>
        )}
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
