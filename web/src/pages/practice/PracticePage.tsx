import { Check, ChevronRight } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import type { PracticeGrouping } from '../../api/endpoints'
import { usePractice, usePractices } from '../../api/queries'
import type { PracticeCard, PracticeGroup, TopicRef } from '../../api/types'
import { Card } from '../../components/ui/Card'
import { Chip } from '../../components/ui/Chip'
import { PageHeader } from '../../components/ui/PageHeader'
import { Segmented } from '../../components/ui/Segmented'
import { cx } from '../../lib/cx'
import { paperName, practiceSource } from '../../lib/labels'
import { AnswerCard } from './AnswerCard'
import { GradedCard } from './GradedCard'
import { PendingAttemptCard } from './PendingAttemptCard'
import styles from './PracticePage.module.css'

const stateLabel: Record<PracticeCard['status'], string> = {
  pending: '未做',
  grading: '批改中',
  graded: '已批改',
  needs_supplement: '需要补充',
  inactive: '已停用',
}

/** 默认选中：地址里指定的练习 → 指定考点的第一道未做 → 全部中的第一道未做。 */
function pickSelected(groups: PracticeGroup[], item: string | null, topic: string | null) {
  const cards = groups.flatMap((group) => group.items)
  if (item && cards.some((card) => card.id === item)) return item
  const scope = topic ? (groups.find((group) => group.id === topic)?.items ?? cards) : cards
  return (scope.find((card) => card.status === 'pending') ?? scope[0] ?? cards[0])?.id
}

type Row = { card: PracticeCard; also: TopicRef[] }
type Section = { group: PracticeGroup; rows: Row[] }

/**
 * 左栏分组：按考点时同一道题只出现在它第一次出现的考点下，其他考点作为标签显示在这一行；
 * 去重后没有题的考点不单独列出。
 */
export function buildSections(groups: PracticeGroup[], grouping: PracticeGrouping): Section[] {
  const seen = new Set<string>()
  const sections: Section[] = []
  for (const group of groups) {
    const rows = group.items
      .filter((card) => !seen.has(card.id))
      .map((card) => ({
        card,
        also: grouping === 'topic' ? card.topics.filter((t) => t.topic_id !== group.id) : [],
      }))
    rows.forEach((row) => seen.add(row.card.id))
    if (rows.length) sections.push({ group, rows })
  }
  return sections
}

function Progress({ cards }: { cards: PracticeCard[] }) {
  return (
    <span className={styles.progress} aria-hidden>
      {cards.map((card) => (
        <i key={card.id} className={styles[card.status]} />
      ))}
    </span>
  )
}

function SectionList({
  section,
  grouping,
  selected,
  linkFor,
}: {
  section: Section
  grouping: PracticeGrouping
  selected: string | undefined
  linkFor: (id: string) => string
}) {
  const { group, rows } = section
  const cards = rows.map((row) => row.card)
  const pending = cards.filter((card) => card.status === 'pending').length
  const allGraded = cards.every((card) => card.status === 'graded')
  const hasSelected = cards.some((card) => card.id === selected)
  const [open, setOpen] = useState(!(allGraded && grouping === 'topic') || hasSelected)
  const title =
    grouping === 'paper' ? (
      paperName(group.label)
    ) : group.id === 'unlinked' ? (
      group.label
    ) : (
      <Link className={styles.topicLink} to={`/topics/${encodeURIComponent(group.id)}`}>
        {group.label}
      </Link>
    )
  const countText = `${cards.length} 道${pending > 0 ? ` · ${pending} 待做` : allGraded ? ' · 已完成' : ''}`
  return (
    <section className={styles.section} aria-label={group.label}>
      <div className={styles.sectionHead}>
        <button
          type="button"
          className={cx(styles.fold, open && styles.open)}
          aria-expanded={open}
          aria-label={open ? `收起${group.label}` : `展开${group.label}`}
          onClick={() => setOpen(!open)}
        >
          <ChevronRight size={14} aria-hidden />
        </button>
        <strong className={styles.sectionTitle}>{title}</strong>
        <small className={styles.sectionCount}>{countText}</small>
      </div>
      <Progress cards={cards} />
      {open && (
        <ul className={styles.items}>
          {rows.map(({ card, also }, index) => {
            const current = card.id === selected
            const source = practiceSource(card.access) || '题库题目'
            return (
              <li key={card.id}>
                <Link
                  to={linkFor(card.id)}
                  className={styles.item}
                  aria-current={current || undefined}
                  data-current={current || undefined}
                  title={`来自${paperName(card.paper_title)}`}
                >
                  <span
                    className={cx(
                      styles.mark,
                      current && card.status === 'pending' ? styles.current : styles[card.status],
                    )}
                  >
                    {card.status === 'graded' && <Check aria-hidden />}
                  </span>
                  <span className={styles.itemText}>
                    <span className={styles.itemTitle}>
                      {grouping === 'topic'
                        ? `第 ${index + 1} 道`
                        : card.topics.map((t) => t.name).join('、') || '练习'}
                    </span>
                    <small className={styles.itemSource}>{source}</small>
                    {also.length > 0 && (
                      <small className={styles.also}>
                        也属于：{also.map((t) => t.name).join('、')}
                      </small>
                    )}
                  </span>
                  <span
                    className={cx(
                      styles.itemState,
                      (current || card.status === 'grading') && styles.active,
                    )}
                  >
                    {current && card.status === 'pending' ? '正在做' : stateLabel[card.status]}
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function SelectedPractice({ card, group }: { card: PracticeCard; group: PracticeGroup }) {
  const { data: detail, isPending } = usePractice(card.id)
  const position = {
    index: group.items.findIndex((item) => item.id === card.id) + 1,
    total: group.items.length,
  }
  if (isPending)
    return (
      <Card padded className={styles.notice}>
        正在读取…
      </Card>
    )
  if (!detail)
    return (
      <Card padded className={styles.notice}>
        这道练习暂时无法显示。
      </Card>
    )
  const stopped = card.status === 'inactive' || !detail.is_current
  const note = stopped ? (detail.review_reason ?? '这道练习已停用，历史作答仍然保留。') : undefined
  const attempt = detail.latest_attempt
  if (attempt && !stopped && (card.status === 'grading' || !attempt.assessment))
    return <PendingAttemptCard card={card} detail={detail} position={position} />
  if (attempt?.assessment)
    return <GradedCard detail={detail} position={position} group={group} note={note} />
  if (stopped)
    return (
      <Card padded className={styles.notice}>
        {note}
      </Card>
    )
  return <AnswerCard key={card.id} detail={detail} position={position} topicName={group.label} />
}

export function PracticePage() {
  const [params, setParams] = useSearchParams()
  const grouping: PracticeGrouping = params.get('view') === 'paper' ? 'paper' : 'topic'
  const includeInactive = params.get('inactive') === '1'
  const { data } = usePractices(grouping, includeInactive)
  const listRef = useRef<HTMLElement>(null)
  const workRef = useRef<HTMLDivElement>(null)
  const selectedId = data
    ? pickSelected(data.items, params.get('item'), params.get('topic'))
    : undefined
  // 换题后：列表里把当前题滚到可见处，右栏回到顶部
  useEffect(() => {
    if (!selectedId) return
    listRef.current?.querySelector('[data-current]')?.scrollIntoView?.({ block: 'nearest' })
    workRef.current?.scrollIntoView?.({ block: 'start' })
  }, [selectedId])
  if (!data) return null

  const selected = selectedId
  const sections = buildSections(data.items, grouping)
  // 待做、批改中、已批改按去重后的题数统计，和列表一致
  const unique = sections.flatMap((section) => section.rows.map((row) => row.card))
  const count = (status: PracticeCard['status']) =>
    unique.filter((card) => card.status === status).length
  const group = data.items.find((g) => g.items.some((item) => item.id === selected))
  const card = group?.items.find((item) => item.id === selected)
  const otherGraded =
    grouping === 'topic' && group
      ? group.items.filter((item) => item.id !== selected && item.status === 'graded')
      : []
  const query = (next: Record<string, string>) => {
    const value = new URLSearchParams({ view: grouping, ...next })
    if (includeInactive) value.set('inactive', '1')
    return value
  }
  const linkFor = (id: string) => `/practice?${query({ item: id })}`

  return (
    <>
      <PageHeader
        title="练习"
        subtitle={
          <div className={styles.summary}>
            <Chip tone="primary">{count('pending')} 道待做</Chip>
            {count('grading') > 0 && <Chip tone="primary">{count('grading')} 道批改中</Chip>}
            <Chip>已批改 {count('graded')} 道</Chip>
            {includeInactive && count('inactive') > 0 && (
              <Chip tone="unknown">已停用 {count('inactive')} 道</Chip>
            )}
          </div>
        }
        actions={
          <div className={styles.headerActions}>
            <label className={styles.toggle}>
              <input
                type="checkbox"
                checked={includeInactive}
                onChange={(event) => {
                  const next = new URLSearchParams(params)
                  if (event.target.checked) next.set('inactive', '1')
                  else next.delete('inactive')
                  setParams(next)
                }}
              />
              显示已停用的练习
            </label>
            <Segmented
              label="练习分组方式"
              items={[
                { value: 'topic', label: '按考点' },
                { value: 'paper', label: '按试卷' },
              ]}
              value={grouping}
              onChange={(view) => {
                const next = new URLSearchParams(params)
                next.set('view', view)
                setParams(next)
              }}
            />
          </div>
        }
      />
      {data.items.length === 0 ? (
        <Card padded className={styles.notice}>
          {includeInactive
            ? '还没有练习。完成一份试卷的逐题分析后，做题龙会为薄弱考点挑选练习。'
            : '现在没有可做的练习。完成一份试卷的逐题分析后，做题龙会为薄弱考点挑选练习；以前停用的练习可以勾选右上角查看。'}
        </Card>
      ) : (
        <div className={styles.layout}>
          <Card className={styles.groupsCard}>
            <aside
              ref={listRef}
              className={styles.groups}
              aria-label={grouping === 'topic' ? '考点分组' : '试卷分组'}
            >
              {sections.map((section) => (
                <SectionList
                  key={`${grouping}-${section.group.id}`}
                  section={section}
                  grouping={grouping}
                  selected={selected}
                  linkFor={linkFor}
                />
              ))}
            </aside>
          </Card>
          <div className={styles.work} ref={workRef}>
            {card && group && <SelectedPractice card={card} group={group} />}
            {otherGraded.map((item) => (
              <OtherGraded key={item.id} card={item} group={group!} />
            ))}
          </div>
        </div>
      )}
    </>
  )
}

/** 同一考点下已批改的其他练习，放在当前练习下方便对照。 */
function OtherGraded({ card, group }: { card: PracticeCard; group: PracticeGroup }) {
  const { data: detail } = usePractice(card.id)
  if (!detail?.latest_attempt?.assessment) return null
  const position = {
    index: group.items.findIndex((item) => item.id === card.id) + 1,
    total: group.items.length,
  }
  return <GradedCard detail={detail} position={position} group={group} />
}
