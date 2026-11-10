import { ArrowRight, ChevronRight, CircleAlert, Flag, Upload } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { endpoints, requestId } from '../../api/endpoints'
import { useAction, useOverview, usePapers, usePractices, useTasks } from '../../api/queries'
import type {
  FeedbackItem,
  Overview,
  Paper,
  PracticeCard,
  PracticeGroup,
  ReviewItem,
} from '../../api/types'
import { ButtonLink } from '../../components/ui/Button'
import { ButtonRow } from '../../components/ui/ButtonRow'
import { Card } from '../../components/ui/Card'
import { Chip } from '../../components/ui/Chip'
import { ErrorState } from '../../components/ui/ErrorState'
import { PageHeader } from '../../components/ui/PageHeader'
import { Skeleton } from '../../components/ui/Skeleton'
import { paperName } from '../../lib/labels'
import { SETUP_GUIDE_PATH, setupMessage } from '../../lib/setup'
import { ProfileBatchPanel } from '../profile/ProfileBatch'
import { weakSpotFacts } from '../../lib/profile'
import styles from './HomePage.module.css'

/*
 * 首页（方向 A · 工作台）：左边“现在做什么”的主卡片和待练考点，右边练习进度、批改中、试卷。
 * “本周”统计、按章聚合的薄弱排行和“按画像来一组”等接口到位后再接；现在只用已有接口能推出的内容。
 */

const weekdays = ['日', '一', '二', '三', '四', '五', '六']
const topicLimit = 5

export function greeting(date: Date) {
  const hour = date.getHours()
  return hour < 5
    ? '夜深了，早点休息'
    : hour < 11
      ? '早上好'
      : hour < 13
        ? '中午好'
        : hour < 18
          ? '下午好'
          : '晚上好'
}

/** 已切好题、等用户核对题号后开始分析的试卷 */
const awaitingAnalysis = (paper: Paper) =>
  !paper.archived_at &&
  paper.counts.total > 0 &&
  (paper.analysis_status === 'segmented' || paper.analysis_status === 'needs_review')

/** 练习出处：原卷练习写试卷名，画像练习写批次名（画像练习的 paper_title 为 null） */
const cameFrom = (card: PracticeCard) =>
  card.paper_title ? `来自${paperName(card.paper_title)}` : (card.batch_title ?? '按画像选的题')

/** 同一道练习可能挂在多个考点下：按考点顺序去重 */
function uniqueCards(groups: PracticeGroup[]) {
  const seen = new Map<string, { card: PracticeCard; group: PracticeGroup }>()
  for (const group of groups)
    for (const card of group.items) if (!seen.has(card.id)) seen.set(card.id, { card, group })
  return [...seen.values()]
}

function MainCard({
  kicker,
  title,
  children,
  actions,
  extra,
}: {
  kicker: string
  title: string
  children: ReactNode
  actions?: ReactNode
  extra?: ReactNode
}) {
  return (
    <Card className={styles.main} aria-label="现在做什么">
      <Chip tone="primary">
        <Flag aria-hidden />
        {kicker}
      </Chip>
      <h2>{title}</h2>
      <p className={styles.lead}>{children}</p>
      {actions && <ButtonRow className={styles.actions}>{actions}</ButtonRow>}
      {extra}
    </Card>
  )
}

function Row({
  to,
  title,
  detail,
  after,
  hint,
}: {
  to: string
  title: string
  detail?: string
  after?: ReactNode
  hint?: string
}) {
  return (
    <li>
      <Link to={to} className={styles.row} title={hint}>
        <span className={styles.rowText}>
          <strong>{title}</strong>
          {detail && <small>{detail}</small>}
        </span>
        {after}
        <ChevronRight size={16} aria-hidden />
      </Link>
    </li>
  )
}

/** 有画像总览时的主卡片：按 next_steps 中第一个可用的建议（顺序固定：继续练习 → 新试卷 → 按画像来一组） */
function overviewMain(
  overview: Overview,
  cards: { card: PracticeCard; group: PracticeGroup }[],
  papers: Paper[],
) {
  const step = overview.next_steps.find((s) => s.available)
  if (step?.kind === 'read_feedback') {
    const items = (overview.feedback?.recent_items ?? []).filter((item) => item.unread)
    return (
      <MainCard
        kicker="新的批改反馈"
        title={`有 ${step.count} 道题批改好了`}
        extra={items.length > 0 && <FeedbackList items={items} />}
      >
        先看看批改反馈，弄清错在哪一步，再继续做新题。
      </MainCard>
    )
  }
  if (step?.kind === 'review_results') {
    const first = overview.review?.items[0]
    return (
      <MainCard
        kicker="需要你核对"
        title={`${step.count} 道题的判断需要核对或补材料`}
        actions={
          <ButtonLink variant="primary" size="lg" to={first ? reviewLink(first) : '/practice'}>
            去核对 <ArrowRight size={16} aria-hidden />
          </ButtonLink>
        }
      >
        {first?.reason ?? step.reason}
      </MainCard>
    )
  }
  if (step?.kind === 'continue_practice') {
    const found = cards.find(({ card }) => card.id === step.target.practice_id)
    const practiceId = step.target.practice_id ?? found?.card.id
    return (
      <MainCard
        kicker="继续练习"
        title={found ? `继续做“${found.group.label}”` : '继续上次的练习'}
        actions={
          <>
            <ButtonLink
              variant="primary"
              size="lg"
              to={practiceId ? `/practice?item=${encodeURIComponent(practiceId)}` : '/practice'}
            >
              继续做 <ArrowRight size={16} aria-hidden />
            </ButtonLink>
            <ButtonLink to="/practice">看全部练习</ButtonLink>
          </>
        }
      >
        {step.reason}
      </MainCard>
    )
  }
  if (step?.kind === 'analyze_paper') {
    const paper = papers.find((p) => p.id === step.target.paper_id)
    return (
      <MainCard
        kicker="有新试卷"
        title={paper ? `${paperName(paper.title)} 等你核对题号` : '有新试卷等你核对题号'}
        actions={
          <ButtonLink
            variant="primary"
            size="lg"
            to={
              step.target.paper_id
                ? `/papers/${encodeURIComponent(step.target.paper_id)}`
                : '/papers'
            }
          >
            去核对 <ArrowRight size={16} aria-hidden />
          </ButtonLink>
        }
      >
        {step.reason}
      </MainCard>
    )
  }
  return (
    <MainCard
      kicker="错题都做完了"
      title="按画像来一组"
      extra={
        <>
          <ProfileBatchPanel overview={overview} />
          <p className={styles.extra}>
            也可以 <Link to="/papers">上传新试卷</Link> 或 <Link to="/bank">在题库里挑题</Link>。
          </p>
        </>
      }
    >
      从你的薄弱考点和该复习的考点里挑题。没做过的考点不会被当成薄弱。
    </MainCard>
  )
}

/** 批改反馈和待核对记录各自的去处 */
const feedbackLink = (item: FeedbackItem) =>
  item.source === 'free_practice' && item.bank_id
    ? `/bank/${encodeURIComponent(item.bank_id)}/practice`
    : item.practice_id
      ? `/practice?item=${encodeURIComponent(item.practice_id)}`
      : '/practice'

function reviewLink(item: ReviewItem) {
  if (item.source === 'free_practice' && item.bank_id)
    return `/bank/${encodeURIComponent(item.bank_id)}/practice`
  if (item.practice_id) return `/practice?item=${encodeURIComponent(item.practice_id)}`
  if (item.paper_id) return `/papers/${encodeURIComponent(item.paper_id)}`
  return '/practice'
}

/** 批改反馈列表：点开时发已读回执（不影响批改结果），未读的带圆点 */
function FeedbackList({ items }: { items: FeedbackItem[] }) {
  const read = useAction(
    (item: FeedbackItem) =>
      endpoints.markFeedbackRead({
        request_id: requestId(),
        source: item.source,
        attempt_id: item.attempt_id,
        feedback_revision: item.feedback_revision,
      }),
    [['profile']],
  )
  return (
    <ul className={styles.rows}>
      {items.slice(0, 3).map((item) => (
        <li key={item.attempt_id}>
          <Link
            to={feedbackLink(item)}
            className={styles.row}
            onClick={() => item.unread && read.mutate(item)}
          >
            {item.unread && <span className={styles.unread} aria-label="未读" />}
            <span className={styles.rowText}>
              <strong>{item.title}</strong>
            </span>
            <Chip
              tone={
                item.correct === true ? 'correct' : item.correct === false ? 'wrong' : 'unknown'
              }
            >
              {item.correct === true ? '做对了' : item.correct === false ? '有错' : '待核对'}
            </Chip>
            <ChevronRight size={16} aria-hidden />
          </Link>
        </li>
      ))}
    </ul>
  )
}

/** 首页“最该补的地方”：画像排行的前 3 个，每个一句依据 */
function WeakSpotsCard({ overview }: { overview: Overview }) {
  return (
    <Card padded className={styles.card} aria-label="最该补的地方">
      <div className={styles.cardHead}>
        <h2>最该补的地方</h2>
        <Link to="/profile" className={styles.more}>
          看完整画像 →
        </Link>
      </div>
      <ul className={styles.rows}>
        {overview.weak_spots.slice(0, 3).map((spot) => (
          <Row
            key={spot.node_id}
            to="/profile"
            title={spot.name}
            detail={spot.basis ?? weakSpotFacts(spot)}
            after={<span className={styles.amount}>错 {spot.recent_failures} 道</span>}
          />
        ))}
      </ul>
    </Card>
  )
}

/** 首页“本周”：只放三个最有用的数字，其余在画像页 */
function WeekCard({ overview }: { overview: Overview }) {
  const s = overview.home_stats
  return (
    <Card padded className={styles.card} aria-label="本周">
      <h2>本周</h2>
      <div className={styles.stats3}>
        <div>
          <b>{s.attempts_this_week}</b>
          <small>道作答</small>
        </div>
        <div>
          <b className={styles.correct}>{s.independent_correct_this_week}</b>
          <small>道独立做对</small>
        </div>
        <div>
          <b className={styles.progressNumber}>{s.grading_count}</b>
          <small>道批改中</small>
        </div>
      </div>
      <ButtonRow className={styles.cardActions}>
        <ButtonLink size="sm" to="/practice">
          去练习
        </ButtonLink>
        <ButtonLink size="sm" variant="ghost" to="/bank">
          在题库里挑题
        </ButtonLink>
        <ButtonLink size="sm" variant="ghost" to="/profile">
          看完整画像
        </ButtonLink>
      </ButtonRow>
    </Card>
  )
}

export function HomePage() {
  const practicesQuery = usePractices('topic')
  const { data: practices } = practicesQuery
  const { data: tasks } = useTasks()
  const papersQuery = usePapers('0')
  const { data: papers } = papersQuery
  // 画像总览接口还没上线或读取失败时，首页退回到只用练习和试卷推出的内容
  const { data: overview } = useOverview()
  const now = new Date()

  const header = (
    <PageHeader
      eyebrow={`${now.getMonth() + 1}月${now.getDate()}日 · 星期${weekdays[now.getDay()]}`}
      title={now.getHours() < 5 ? greeting(now) : `${greeting(now)}，先从最要紧的一件开始`}
    />
  )
  if (practicesQuery.error || papersQuery.error)
    return (
      <>
        {header}
        <ErrorState
          error={practicesQuery.error ?? papersQuery.error}
          onRetry={() => {
            void practicesQuery.refetch()
            void papersQuery.refetch()
          }}
        />
      </>
    )
  if (!practices || !papers)
    return (
      <>
        {header}
        <div className={styles.grid}>
          <Skeleton />
          <Skeleton variant="rows" rows={4} />
        </div>
      </>
    )

  const cards = uniqueCards(practices.items)
  const pending = cards.filter(({ card }) => card.status === 'pending')
  const grading = cards.filter(({ card }) => card.status === 'grading')
  const graded = cards.filter(({ card }) => card.status === 'graded')
  const pendingGroups = practices.items
    .map((group) => ({ group, items: group.items.filter((item) => item.status === 'pending') }))
    .filter((entry) => entry.items.length > 0)
  const unavailable = tasks?.availability.status === 'unavailable'
  const waitingPaper = papers.items.find(awaitingAnalysis)
  const analysed = papers.items.filter((paper) => paper.analysis_status === 'diagnosed')
  const latestPaper = [...papers.items].sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
  const next = pending[0]
  const nextGroupLeft = next
    ? next.group.items.filter((item) => item.status === 'pending').length
    : 0

  const paperLine = waitingPaper && (
    <p className={styles.extra}>
      另外：
      <Link to={`/papers/${encodeURIComponent(waitingPaper.id)}`}>
        {paperName(waitingPaper.title)} 等你核对题号 →
      </Link>
    </p>
  )
  const fromOverview = overview && papers.total > 0 && overviewMain(overview, cards, papers.items)
  const main = fromOverview ? (
    fromOverview
  ) : papers.total === 0 ? (
    <MainCard
      kicker="开始"
      title="上传第一份做过的试卷"
      actions={
        <ButtonLink variant="primary" size="lg" to="/papers">
          <Upload size={16} aria-hidden /> 去上传
        </ButtonLink>
      }
    >
      黑笔为考试作答，红笔为事后批改。做题龙会逐题分析，再针对薄弱考点挑选练习。
    </MainCard>
  ) : next ? (
    <MainCard
      kicker="继续练习"
      title={`“${next.group.label}” 还有 ${nextGroupLeft} 道没做`}
      actions={
        <>
          <ButtonLink variant="primary" size="lg" to={`/practice?item=${next.card.id}`}>
            继续做 <ArrowRight size={16} aria-hidden />
          </ButtonLink>
          <ButtonLink to="/practice">看全部练习</ButtonLink>
        </>
      }
      extra={paperLine}
    >
      {cameFrom(next.card)}的薄弱考点。一共还有 {pending.length} 道练习待做。
    </MainCard>
  ) : waitingPaper ? (
    <MainCard
      kicker="有新试卷"
      title={`${paperName(waitingPaper.title)} 等你核对题号`}
      actions={
        <ButtonLink
          variant="primary"
          size="lg"
          to={`/papers/${encodeURIComponent(waitingPaper.id)}`}
        >
          去核对 <ArrowRight size={16} aria-hidden />
        </ButtonLink>
      }
    >
      做题龙切出了 {waitingPaper.counts.total}{' '}
      道题。核对题号后开始逐题分析，分析完会为薄弱考点挑练习。
    </MainCard>
  ) : (
    <MainCard
      kicker="都做完了"
      title="练习都做完了"
      actions={
        <>
          <ButtonLink variant="primary" size="lg" to="/papers">
            <Upload size={16} aria-hidden /> 上传新试卷
          </ButtonLink>
          <ButtonLink to="/bank">在题库里挑题</ButtonLink>
          <ButtonLink variant="ghost" to="/profile">
            看完整画像
          </ButtonLink>
        </>
      }
    >
      可以上传新做的试卷，或者在题库里按考点挑几道题自己练。
    </MainCard>
  )

  return (
    <>
      {header}
      {unavailable && tasks && (
        <div className={styles.banner} role="status">
          <CircleAlert size={16} aria-hidden />
          <span>{setupMessage(tasks.availability)}</span>
          <Link to={SETUP_GUIDE_PATH}>查看准备步骤</Link>
        </div>
      )}
      <div className={styles.grid}>
        <div className={styles.column}>
          {main}

          {overview && overview.weak_spots.length > 0 ? (
            <WeakSpotsCard overview={overview} />
          ) : (
            pendingGroups.length > 0 && (
              <Card padded className={styles.card} aria-label="待练的考点">
                <div className={styles.cardHead}>
                  <h2>待练的考点</h2>
                  <Link to="/profile" className={styles.more}>
                    看完整画像 →
                  </Link>
                </div>
                <ul className={styles.rows}>
                  {pendingGroups.slice(0, topicLimit).map(({ group, items }) => (
                    <Row
                      key={group.id}
                      to={`/practice?item=${items[0].id}`}
                      title={group.label}
                      hint={[...new Set(items.map(cameFrom))].join('、')}
                      after={
                        items.length > 1 && (
                          <span className={styles.amount}>{items.length} 道待做</span>
                        )
                      }
                    />
                  ))}
                </ul>
                {pendingGroups.length > topicLimit && (
                  <Link to="/practice" className={styles.moreRow}>
                    还有 {pendingGroups.length - topicLimit} 个考点 · 去练习 →
                  </Link>
                )}
              </Card>
            )
          )}

          {overview?.next_steps.find((step) => step.available)?.kind ===
          'read_feedback' ? null : overview?.feedback &&
            overview.feedback.recent_items.length > 0 ? (
            <Card padded className={styles.card} aria-label="最近批改">
              <div className={styles.cardHead}>
                <h2>最近批改</h2>
                {overview.feedback.unread_count > 0 && (
                  <span className={styles.faint}>{overview.feedback.unread_count} 道没看</span>
                )}
              </div>
              <FeedbackList items={overview.feedback.recent_items} />
            </Card>
          ) : (
            graded.length > 0 && (
              <Card padded className={styles.card} aria-label="最近批改">
                <div className={styles.cardHead}>
                  <h2>最近批改</h2>
                  <span className={styles.faint}>点开看批改反馈</span>
                </div>
                <ul className={styles.rows}>
                  {graded.slice(0, 3).map(({ card, group }) => (
                    <Row
                      key={card.id}
                      to={`/practice?item=${card.id}`}
                      title={group.label}
                      detail={cameFrom(card)}
                      after={<Chip>已批改</Chip>}
                    />
                  ))}
                </ul>
              </Card>
            )
          )}
        </div>

        <div className={styles.column}>
          {overview ? (
            <WeekCard overview={overview} />
          ) : (
            <Card padded className={styles.card} aria-label="练习进度">
              <h2>练习进度</h2>
              <div className={styles.stats}>
                <div>
                  <b>{pending.length}</b>
                  <small>道待做</small>
                </div>
                <div>
                  <b>{graded.length}</b>
                  <small>道已批改</small>
                </div>
              </div>
              <ButtonRow className={styles.cardActions}>
                <ButtonLink size="sm" to="/practice">
                  去练习
                </ButtonLink>
                <ButtonLink size="sm" variant="ghost" to="/bank">
                  在题库里挑题
                </ButtonLink>
              </ButtonRow>
            </Card>
          )}

          {(grading.length > 0 || (tasks && (tasks.active || tasks.queued_count > 0))) && (
            <Card padded className={styles.card} aria-label="正在进行">
              <h2>正在进行</h2>
              <ul className={styles.rows}>
                {grading.slice(0, 3).map(({ card, group }) => (
                  <Row
                    key={card.id}
                    to={`/practice?item=${card.id}`}
                    title={`批改：${group.label}`}
                    detail="一般 1～2 分钟出结果"
                  />
                ))}
                {tasks?.active && !tasks.active.attempt_id && (
                  <li className={styles.plainRow}>
                    <span className={styles.spinner} aria-hidden />
                    做题龙{tasks.active.progress.message}
                  </li>
                )}
                {tasks && !tasks.active && tasks.queued_count > 0 && (
                  <li className={styles.plainRow}>
                    {tasks.queued_count} 项在排队
                    {tasks.availability.status === 'unavailable'
                      ? '，学习服务准备好后会自动开始'
                      : '，会按顺序自动开始'}
                  </li>
                )}
              </ul>
              {grading.length > 3 && (
                <p className={styles.faint}>另有 {grading.length - 3} 道在批改</p>
              )}
            </Card>
          )}

          <Card padded className={styles.card} aria-label="试卷">
            <h2>试卷</h2>
            <p className={styles.muted}>
              {papers.total === 0
                ? '还没有上传试卷。'
                : `共 ${papers.total} 份，已分析 ${analysed.length} 份${latestPaper ? ` · 最近一份${paperName(latestPaper.title)}` : ''}`}
            </p>
            <ButtonRow className={styles.cardActions}>
              <ButtonLink size="sm" to="/papers">
                <Upload size={14} aria-hidden /> 上传新试卷
              </ButtonLink>
              {papers.total > 0 && (
                <ButtonLink size="sm" variant="ghost" to="/papers">
                  全部试卷
                </ButtonLink>
              )}
            </ButtonRow>
          </Card>
        </div>
      </div>
    </>
  )
}
