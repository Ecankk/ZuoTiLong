import { ArrowRight, ChevronRight, CircleAlert, Flag, Upload } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { usePapers, usePractices, useTasks } from '../../api/queries'
import type { Paper, PracticeCard, PracticeGroup } from '../../api/types'
import { ButtonLink } from '../../components/ui/Button'
import { ButtonRow } from '../../components/ui/ButtonRow'
import { Card } from '../../components/ui/Card'
import { Chip } from '../../components/ui/Chip'
import { ErrorState } from '../../components/ui/ErrorState'
import { PageHeader } from '../../components/ui/PageHeader'
import { Skeleton } from '../../components/ui/Skeleton'
import { paperName } from '../../lib/labels'
import { SETUP_GUIDE_PATH, setupMessage } from '../../lib/setup'
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
  actions: ReactNode
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
      <ButtonRow className={styles.actions}>{actions}</ButtonRow>
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

export function HomePage() {
  const practicesQuery = usePractices('topic')
  const { data: practices } = practicesQuery
  const { data: tasks } = useTasks()
  const papersQuery = usePapers('0')
  const { data: papers } = papersQuery
  const now = new Date()

  const header = (
    <PageHeader
      eyebrow={`${now.getMonth() + 1}月${now.getDate()}日 · 星期${weekdays[now.getDay()]}`}
      title={`${greeting(now)}，先从最要紧的一件开始`}
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
  const main =
    papers.total === 0 ? (
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
        来自{paperName(next.card.paper_title)}的薄弱考点。一共还有 {pending.length} 道练习待做。
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

          {pendingGroups.length > 0 && (
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
                    hint={`来自${[...new Set(items.map((i) => paperName(i.paper_title)))].join('、')}`}
                    after={<span className={styles.amount}>{items.length} 道待做</span>}
                  />
                ))}
              </ul>
              {pendingGroups.length > topicLimit && (
                <Link to="/practice" className={styles.moreRow}>
                  还有 {pendingGroups.length - topicLimit} 个考点 · 去练习 →
                </Link>
              )}
            </Card>
          )}

          {graded.length > 0 && (
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
                    detail={`来自${paperName(card.paper_title)}`}
                    after={<Chip>已批改</Chip>}
                  />
                ))}
              </ul>
            </Card>
          )}
        </div>

        <div className={styles.column}>
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
