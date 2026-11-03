import { Check } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'
import type { PracticeGrouping } from '../../api/endpoints'
import { usePractice, usePractices } from '../../api/queries'
import type { PracticeCard, PracticeGroup } from '../../api/types'
import { Card } from '../../components/ui/Card'
import { Chip } from '../../components/ui/Chip'
import { PageHeader } from '../../components/ui/PageHeader'
import { Segmented } from '../../components/ui/Segmented'
import { cx } from '../../lib/cx'
import { paperName, sourceName } from '../../lib/labels'
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

function GroupCard({
  group,
  grouping,
  selected,
  linkFor,
}: {
  group: PracticeGroup
  grouping: PracticeGrouping
  selected: string | undefined
  linkFor: (id: string) => string
}) {
  const allGraded = group.items.every((item) => item.status === 'graded')
  const papers = [...new Set(group.items.map((item) => paperName(item.paper_title)))]
  const subtitle =
    grouping === 'topic'
      ? allGraded
        ? `已完成 · ${group.items.length} 道都批改了`
        : `来自${papers.join('、')}`
      : `${group.items.length} 道练习`
  return (
    <Card className={cx(styles.group, allGraded && grouping === 'topic' && styles.done)}>
      <div className={styles.groupHead}>
        <strong>{grouping === 'paper' ? paperName(group.label) : group.label}</strong>
        <small>
          <span>{subtitle}</span>
          <span className={styles.dots} aria-hidden>
            {group.items.map((item) => (
              <i key={item.id} className={styles[item.status]} />
            ))}
          </span>
        </small>
      </div>
      {!(allGraded && grouping === 'topic') && (
        <ul className={styles.items}>
          {group.items.map((item, index) => {
            const current = item.id === selected
            return (
              <li key={item.id}>
                <Link
                  to={linkFor(item.id)}
                  className={styles.item}
                  aria-current={current || undefined}
                >
                  <span
                    className={cx(
                      styles.mark,
                      current && item.status === 'pending' ? styles.current : styles[item.status],
                    )}
                  >
                    {item.status === 'graded' && <Check aria-hidden />}
                  </span>
                  <span className={styles.itemText}>
                    {grouping === 'topic'
                      ? `第 ${index + 1} 道 · ${sourceName(item.access)}`
                      : `${item.topics[0]?.name ?? '练习'} · ${sourceName(item.access)}`}
                  </span>
                  <span
                    className={cx(
                      styles.itemState,
                      (current || item.status === 'grading') && styles.active,
                    )}
                  >
                    {current && item.status === 'pending' ? '正在做' : stateLabel[item.status]}
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
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
  if (!data) return null

  const selected = pickSelected(data.items, params.get('item'), params.get('topic'))
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
            <Chip tone="primary">{data.counts.pending} 道待做</Chip>
            {data.counts.grading > 0 && <Chip tone="primary">{data.counts.grading} 道批改中</Chip>}
            <Chip>已批改 {data.counts.graded} 道</Chip>
            {includeInactive && data.counts.inactive > 0 && (
              <Chip tone="unknown">已停用 {data.counts.inactive} 道</Chip>
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
          <aside
            className={styles.groups}
            aria-label={grouping === 'topic' ? '考点分组' : '试卷分组'}
          >
            {data.items.map((g) => (
              <GroupCard
                key={g.id}
                group={g}
                grouping={grouping}
                selected={selected}
                linkFor={linkFor}
              />
            ))}
          </aside>
          <div className={styles.work}>
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
