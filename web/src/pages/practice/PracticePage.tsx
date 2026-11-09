import { useQueries } from '@tanstack/react-query'
import { ArrowRight, Check, ChevronDown, ChevronRight, Search, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { endpoints, type PracticeGrouping } from '../../api/endpoints'
import { queryKeys, usePractice, usePractices } from '../../api/queries'
import type { PracticeCard, PracticeGroup } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Button, ButtonLink } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { CorrectnessChip } from '../../components/ui/Chip'
import { PageHeader } from '../../components/ui/PageHeader'
import { Segmented } from '../../components/ui/Segmented'
import { cx } from '../../lib/cx'
import { assessmentCorrectness, paperName, practiceSource } from '../../lib/labels'
import { AnswerCard } from './AnswerCard'
import { GradedCard, type NextPractice } from './GradedCard'
import { PendingAttemptCard } from './PendingAttemptCard'
import {
  bucketLabel,
  buckets,
  buildSections,
  filterSections,
  nextTodo,
  originLabel,
  origins,
  pickSelected,
  practiceBucket,
  practiceOrigin,
  rowState,
  type Bucket,
  type Origin,
  type Results,
  type Row,
  type Section,
} from './selection'
import styles from './PracticePage.module.css'

export { buildSections }

const isBucket = (value: string | null): value is Bucket => buckets.includes(value as Bucket)
const isOrigin = (value: string | null): value is Origin => origins.includes(value as Origin)

/** 已批改练习的对错：列表接口不带，逐道读详情（和右栏共用缓存）。 */
function useResults(cards: PracticeCard[]): Results {
  const graded = cards.filter((card) => card.status === 'graded')
  const details = useQueries({
    queries: graded.map((card) => ({
      queryKey: queryKeys.practice(card.id),
      queryFn: () => endpoints.practice(card.id),
    })),
  })
  return Object.fromEntries(
    graded.map((card, index) => {
      const assessment = details[index]?.data?.latest_attempt?.assessment
      return [card.id, assessment ? assessmentCorrectness(assessment) : undefined]
    }),
  )
}

/** 一道题在列表里的标题和出处 */
function rowText(row: Row, section: Section, grouping: PracticeGrouping, single: boolean) {
  const { card } = row
  const source = practiceSource(card.access) || '练习题'
  const topics = card.topics.map((t) => t.name).join('、')
  if (grouping === 'topic') return { title: single ? section.group.label : '', source }
  const paper = card.paper_title ? paperName(card.paper_title) : ''
  return single
    ? { title: paper || topics || '练习', source: [topics, source].filter(Boolean).join(' · ') }
    : { title: topics || '练习', source }
}

function Mark({
  card,
  results,
  current,
}: {
  card: PracticeCard
  results: Results
  current: boolean
}) {
  const bucket = practiceBucket(card, results)
  return (
    <span
      className={cx(
        styles.mark,
        current && bucket === 'todo' ? styles.current : styles[card.status],
        bucket === 'right' && styles.right,
        bucket === 'wrong' && styles.wrong,
      )}
    >
      {bucket === 'right' && <Check aria-hidden />}
      {bucket === 'wrong' && <X aria-hidden />}
      {card.status === 'graded' && !bucket && <Check aria-hidden />}
    </span>
  )
}

function ItemLink({
  row,
  section,
  grouping,
  single,
  index,
  selected,
  results,
  linkFor,
}: {
  row: Row
  section: Section
  grouping: PracticeGrouping
  single: boolean
  index: number
  selected: string | undefined
  results: Results
  linkFor: (id: string) => string
}) {
  const { card, also } = row
  const current = card.id === selected
  const text = rowText(row, section, grouping, single)
  const origin = practiceOrigin(card)
  const state = rowState(card, results, current)
  return (
    <Link
      to={linkFor(card.id)}
      className={cx(styles.item, single && styles.single)}
      aria-current={current || undefined}
      data-current={current || undefined}
      title={[
        card.paper_title && `来自${paperName(card.paper_title)}`,
        also.length > 0 && `也属于：${also.map((t) => t.name).join('、')}`,
      ]
        .filter(Boolean)
        .join('\n')}
    >
      <Mark card={card} results={results} current={current} />
      <span className={styles.itemText}>
        <span className={styles.itemTitle}>{text.title || `第 ${index + 1} 道`}</span>
        <small className={styles.itemSource}>
          {text.source}
          {origin && origin !== 'paper' && (
            <span className={styles.originTag}>{originLabel[origin]}</span>
          )}
        </small>
        {!single && also.length > 0 && (
          <small className={styles.also}>也属于：{also.map((t) => t.name).join('、')}</small>
        )}
      </span>
      <span
        className={cx(
          styles.itemState,
          (current || card.status === 'grading') && styles.active,
          state === '做对' && styles.stateRight,
          (state === '做错' || state === '部分对') && styles.stateWrong,
        )}
      >
        {state}
      </span>
    </Link>
  )
}

function Progress({ cards, results }: { cards: PracticeCard[]; results: Results }) {
  return (
    <span className={styles.progress} aria-hidden>
      {cards.map((card) => (
        <i
          key={card.id}
          className={cx(styles[card.status], styles[practiceBucket(card, results) ?? 'none'])}
        />
      ))}
    </span>
  )
}

/**
 * 一组练习。只有一道题的组压成一行（“条件概率 · 2026 数学一 · 第 10 题”）；
 * 多道题的组默认展开当前题所在的组和还有题没做完的组，全部做完的组收起。
 */
function SectionList({
  section,
  grouping,
  selected,
  results,
  filtered,
  linkFor,
}: {
  section: Section
  grouping: PracticeGrouping
  selected: string | undefined
  results: Results
  filtered: boolean
  linkFor: (id: string) => string
}) {
  const { group, rows } = section
  const cards = rows.map((row) => row.card)
  const unfinished = cards.filter((card) => {
    const bucket = practiceBucket(card, results)
    return bucket === 'todo' || bucket === 'waiting'
  }).length
  const todo = cards.filter((card) => practiceBucket(card, results) === 'todo').length
  const hasSelected = cards.some((card) => card.id === selected)
  const [open, setOpen] = useState(filtered || hasSelected || unfinished > 0)
  if (rows.length === 1)
    return (
      <section className={styles.section} aria-label={group.label}>
        <ItemLink
          row={rows[0]}
          section={section}
          grouping={grouping}
          single
          index={0}
          selected={selected}
          results={results}
          linkFor={linkFor}
        />
      </section>
    )
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
  const countText = `${cards.length} 道${todo > 0 ? ` · ${todo} 未做` : unfinished === 0 ? ' · 已完成' : ''}`
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
      <Progress cards={cards} results={results} />
      {open && (
        <ul className={styles.items}>
          {rows.map((row, index) => (
            <li key={row.card.id}>
              <ItemLink
                row={row}
                section={section}
                grouping={grouping}
                single={false}
                index={index}
                selected={selected}
                results={results}
                linkFor={linkFor}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** 卡片标题上面那一行：按考点时“考点 · 第 i / n 道”，按试卷时“考点 · 《试卷》第 i / n 道”。 */
function eyebrowFor(card: PracticeCard, group: PracticeGroup, grouping: PracticeGrouping) {
  // 一组只有一道题时不写“第 1 / 1 道”
  const position =
    group.items.length > 1
      ? `第 ${group.items.findIndex((item) => item.id === card.id) + 1} / ${group.items.length} 道`
      : ''
  if (grouping === 'topic') return [group.label, position].filter(Boolean).join(' · ')
  const topics = card.topics.map((t) => t.name).join('、')
  return [topics, `${paperName(group.label)}${position}`].filter(Boolean).join(' · ')
}

function SelectedPractice({
  card,
  eyebrow,
  next,
}: {
  card: PracticeCard
  eyebrow: string
  next?: NextPractice
}) {
  const { data: detail, isPending, isError, refetch } = usePractice(card.id)
  if (isPending)
    return (
      <Card padded className={styles.notice} role="status">
        正在读取这道练习…
      </Card>
    )
  if (isError)
    return (
      <Card padded className={styles.notice}>
        <p>这道练习没有读出来，请确认做题龙还开着。</p>
        <Button size="sm" onClick={() => void refetch()}>
          重试
        </Button>
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
    return <PendingAttemptCard card={card} detail={detail} eyebrow={eyebrow} />
  if (attempt?.assessment)
    return <GradedCard detail={detail} eyebrow={eyebrow} next={next} note={note} />
  if (stopped)
    return (
      <Card padded className={styles.notice}>
        {note}
      </Card>
    )
  return <AnswerCard key={card.id} detail={detail} eyebrow={eyebrow} />
}

/** 右栏底部：接下来做哪道。当前题还没做时是“先跳过”，做完了是“做下一道”。 */
function NextBar({
  next,
  currentTodo,
  allDone,
}: {
  next?: NextPractice
  currentTodo: boolean
  allDone: boolean
}) {
  if (!next)
    return allDone ? (
      <Card padded className={styles.nextBar}>
        <span className={styles.nextText}>
          <small>进度</small>
          <strong>没做的练习都做完了。</strong>
        </span>
        <ButtonLink size="sm" variant="ghost" to="/bank">
          去题库自由练习
        </ButtonLink>
      </Card>
    ) : null
  return (
    <Card padded className={styles.nextBar}>
      <span className={styles.nextText}>
        <small>{currentTodo ? '不想做这道？' : '下一道没做的'}</small>
        <strong>{next.label}</strong>
      </span>
      <ButtonLink size="sm" variant={currentTodo ? 'ghost' : 'primary'} to={next.to}>
        {currentTodo ? '先跳过，做下一道' : '做下一道'}
        <ArrowRight size={14} aria-hidden />
      </ButtonLink>
    </Card>
  )
}

/** 做过的一道：出处、对错和结论的第一句，点进去再看完整反馈。 */
function OtherRow({ card, linkFor }: { card: PracticeCard; linkFor: (id: string) => string }) {
  const { data: detail } = usePractice(card.id)
  const assessment = detail?.latest_attempt?.assessment
  const lead = assessment?.feedback.split(/\n+/).find((line) => line.trim())
  return (
    <Link to={linkFor(card.id)} className={styles.otherRow}>
      <span className={styles.otherText}>
        <strong>{practiceSource(card.access) || '练习题'}</strong>
        {lead && (
          <small>
            <MathText text={lead.trim()} />
          </small>
        )}
      </span>
      {assessment ? (
        <CorrectnessChip value={assessmentCorrectness(assessment)} />
      ) : (
        <small>已批改</small>
      )}
      <ArrowRight size={14} aria-hidden />
    </Link>
  )
}

/** 同一考点下做过的其他题：一行一道，不在这里整张展开。 */
function OtherGraded({
  cards,
  linkFor,
}: {
  cards: PracticeCard[]
  linkFor: (id: string) => string
}) {
  if (!cards.length) return null
  return (
    <Card padded className={styles.others} aria-label="这个考点做过的题">
      <h3>这个考点做过的题</h3>
      <ul>
        {cards.map((card) => (
          <li key={card.id}>
            <OtherRow card={card} linkFor={linkFor} />
          </li>
        ))}
      </ul>
    </Card>
  )
}

/** 顶部进度：一条分段条加一句“已做 4 / 59 道 · 做对 3 · 做错 1”。 */
function Overview({ counts, total }: { counts: Record<Bucket, number>; total: number }) {
  const done = counts.right + counts.wrong
  const parts = [
    `已做 ${done + counts.waiting} / ${total} 道`,
    counts.right > 0 && `做对 ${counts.right}`,
    counts.wrong > 0 && `做错 ${counts.wrong}`,
    counts.waiting > 0 && `待批改 ${counts.waiting}`,
  ].filter(Boolean)
  return (
    <div className={styles.summary}>
      <span className={styles.overviewBar} aria-hidden>
        {(['right', 'wrong', 'waiting'] as const).map((bucket) =>
          counts[bucket] > 0 ? (
            <i
              key={bucket}
              className={styles[bucket]}
              style={{ width: `${(counts[bucket] / Math.max(total, 1)) * 100}%` }}
            />
          ) : null,
        )}
      </span>
      <span>{parts.join(' · ')}</span>
    </div>
  )
}

function FilterPills<T extends string>({
  label,
  value,
  items,
  onChange,
}: {
  label: string
  value: T | undefined
  items: { value: T; label: string; count?: number }[]
  onChange: (value: T | undefined) => void
}) {
  return (
    <div className={styles.pills} role="group" aria-label={label}>
      <button type="button" aria-pressed={!value} onClick={() => onChange(undefined)}>
        全部
      </button>
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          aria-pressed={value === item.value}
          onClick={() => onChange(value === item.value ? undefined : item.value)}
        >
          {item.label}
          {item.count !== undefined && <b>{item.count}</b>}
        </button>
      ))}
    </div>
  )
}

export function PracticePage() {
  const [params, setParams] = useSearchParams()
  const grouping: PracticeGrouping = params.get('view') === 'paper' ? 'paper' : 'topic'
  const includeInactive = params.get('inactive') === '1'
  const statusParam = params.get('status')
  const sourceParam = params.get('source')
  const status = isBucket(statusParam) ? statusParam : undefined
  const source = isOrigin(sourceParam) ? sourceParam : undefined
  const [query, setQuery] = useState('')
  // 窄窗口的题目列表：记下打开时选中的是哪道，换了题自然就收起
  const [openedAt, setOpenedAt] = useState<string | null>(null)
  const { data, isError, refetch } = usePractices(grouping, includeInactive)
  const listRef = useRef<HTMLElement>(null)
  const workRef = useRef<HTMLDivElement>(null)

  const sections = useMemo(
    () => (data ? buildSections(data.items, grouping) : []),
    [data, grouping],
  )
  const unique = useMemo(
    () => sections.flatMap((section) => section.rows.map((row) => row.card)),
    [sections],
  )
  const results = useResults(unique)
  const selectedId = data
    ? pickSelected(data.items, {
        item: params.get('item'),
        topic: params.get('topic'),
        paper: params.get('paper'),
      })
    : undefined
  const listOpen = openedAt !== null && openedAt === (selectedId ?? '')
  const setListOpen = (open: boolean) => setOpenedAt(open ? (selectedId ?? '') : null)

  // 列表浮层打开时按 Esc 收起
  useEffect(() => {
    if (!listOpen) return
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenedAt(null)
    }
    document.addEventListener('keydown', close)
    return () => document.removeEventListener('keydown', close)
  }, [listOpen])

  // 换题后：列表里把当前题滚到可见处，右栏回到顶部
  useEffect(() => {
    if (!selectedId) return
    listRef.current?.querySelector('[data-current]')?.scrollIntoView?.({ block: 'nearest' })
    workRef.current?.scrollIntoView?.({ block: 'start' })
  }, [selectedId])

  if (!data)
    return (
      <>
        <PageHeader title="练习" />
        <Card padded className={styles.notice} role={isError ? undefined : 'status'}>
          {isError ? (
            <>
              <p>练习列表没有读出来，请确认做题龙还开着。</p>
              <Button size="sm" onClick={() => void refetch()}>
                重试
              </Button>
            </>
          ) : (
            '正在读取练习…'
          )}
        </Card>
      </>
    )

  const selected = selectedId
  const filter = { status, source, query }
  // 状态计数跟着来源和搜索走，和列表对得上
  const scoped = filterSections(sections, { source, query }, results)
  const scopedCards = scoped.flatMap((section) => section.rows.map((row) => row.card))
  const counts = Object.fromEntries(
    buckets.map((bucket) => [
      bucket,
      scopedCards.filter((card) => practiceBucket(card, results) === bucket).length,
    ]),
  ) as Record<Bucket, number>
  const allCounts = Object.fromEntries(
    buckets.map((bucket) => [
      bucket,
      unique.filter((card) => practiceBucket(card, results) === bucket).length,
    ]),
  ) as Record<Bucket, number>
  const present = origins.filter((origin) => unique.some((card) => practiceOrigin(card) === origin))
  const filtering = Boolean(status || source || query.trim())
  const visible = filterSections(sections, filter, results, selected)

  const group = data.items.find((g) => g.items.some((item) => item.id === selected))
  const card = group?.items.find((item) => item.id === selected)
  const eyebrow = card && group ? eyebrowFor(card, group, grouping) : ''
  const otherGraded =
    grouping === 'topic' && group
      ? group.items.filter((item) => item.id !== selected && item.status === 'graded')
      : []

  const link = (next: Record<string, string | undefined>) => {
    const value = new URLSearchParams({ view: grouping })
    if (includeInactive) value.set('inactive', '1')
    if (status) value.set('status', status)
    if (source) value.set('source', source)
    for (const [key, item] of Object.entries(next)) {
      if (item) value.set(key, item)
      else value.delete(key)
    }
    return value
  }
  const linkFor = (id: string) => `/practice?${link({ item: id })}`
  const setFilter = (change: Record<string, string | undefined>) =>
    setParams(link({ item: selected, ...change }))

  // 下一道：先在筛选后的列表里找，找不到再在全部里找
  const nextCard = nextTodo(visible, selected, results) ?? nextTodo(sections, selected, results)
  const next: NextPractice | undefined = nextCard && {
    to: linkFor(nextCard.id),
    label: [
      nextCard.topics.map((t) => t.name).join('、'),
      practiceSource(nextCard.access) || '练习题',
    ]
      .filter(Boolean)
      .join(' · '),
  }
  const currentTodo = card ? practiceBucket(card, results) === 'todo' : false

  return (
    <>
      <PageHeader
        title="练习"
        subtitle={<Overview counts={allCounts} total={unique.length} />}
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
        <div className={styles.layout} data-list-open={listOpen || undefined}>
          {/* 窄窗口：列表收成一条，点开后浮在上面 */}
          <div className={styles.switcher}>
            <span className={styles.switcherText}>
              <small>当前</small>
              <strong>{eyebrow || '还没选题'}</strong>
            </span>
            <Button
              size="sm"
              aria-expanded={listOpen}
              aria-controls="practice-list"
              onClick={() => setListOpen(!listOpen)}
            >
              {listOpen ? '收起列表' : '切换题目'}
              <ChevronDown size={14} aria-hidden className={cx(listOpen && styles.flip)} />
            </Button>
          </div>
          <Card className={styles.groupsCard} id="practice-list">
            <div className={styles.filters}>
              <label className={styles.search}>
                <Search size={14} aria-hidden />
                <input
                  type="search"
                  aria-label="搜索考点或试卷"
                  placeholder="搜索考点或试卷"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Escape') setQuery('')
                  }}
                />
              </label>
              <FilterPills
                label="按状态筛选"
                value={status}
                items={buckets
                  // 数量为 0 的类别不占位置（未做和正在用的筛选除外）
                  .filter((bucket) => bucket === 'todo' || counts[bucket] > 0 || bucket === status)
                  .map((bucket) => ({
                    value: bucket,
                    label: bucketLabel[bucket],
                    count: counts[bucket],
                  }))}
                onChange={(value) => setFilter({ status: value })}
              />
              {(present.length > 1 || source) && (
                <FilterPills
                  label="按来源筛选"
                  value={source}
                  items={present.map((origin) => ({ value: origin, label: originLabel[origin] }))}
                  onChange={(value) => setFilter({ source: value })}
                />
              )}
            </div>
            <aside
              ref={listRef}
              className={styles.groups}
              aria-label={grouping === 'topic' ? '考点分组' : '试卷分组'}
            >
              {visible.map((section) => (
                <SectionList
                  key={`${grouping}-${section.group.id}-${status ?? ''}-${source ?? ''}-${filtering}`}
                  section={section}
                  grouping={grouping}
                  selected={selected}
                  results={results}
                  filtered={filtering}
                  linkFor={linkFor}
                />
              ))}
              {filtering && visible.every((s) => s.rows.every((r) => r.card.id === selected)) && (
                <div className={styles.empty}>
                  <p>没有符合条件的练习。</p>
                  <Button
                    size="sm"
                    onClick={() => {
                      setQuery('')
                      setFilter({ status: undefined, source: undefined })
                    }}
                  >
                    清除筛选
                  </Button>
                </div>
              )}
            </aside>
          </Card>
          <div className={styles.work} ref={workRef}>
            {card && group && <SelectedPractice card={card} eyebrow={eyebrow} next={next} />}
            {card && (
              <NextBar
                next={next}
                currentTodo={currentTodo}
                allDone={allCounts.todo === 0 && !currentTodo}
              />
            )}
            <OtherGraded cards={otherGraded} linkFor={linkFor} />
          </div>
        </div>
      )}
    </>
  )
}
