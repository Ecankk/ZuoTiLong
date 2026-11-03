import {
  ArrowRight,
  ChevronRight,
  Clock,
  Flag,
  LoaderCircle,
  PencilLine,
  type LucideIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { usePapers, usePractices, useTasks } from '../../api/queries'
import type { PracticeGroup } from '../../api/types'
import { useOpenOnboarding } from '../../components/onboarding/Onboarding'
import { Button, ButtonLink } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip } from '../../components/ui/Chip'
import { PageHeader } from '../../components/ui/PageHeader'
import { cx } from '../../lib/cx'
import { paperName } from '../../lib/labels'
import styles from './HomePage.module.css'

/*
 * 首页规则、统计、待核对与新反馈的接口还没有提供（契约留到后续批次）。
 * 这里只显示能从现有接口推出的部分：待做练习、批改中、后台进度、AI 服务与上传提示。
 */

const weekdays = ['日', '一', '二', '三', '四', '五', '六']

function greeting(date: Date) {
  const hour = date.getHours()
  return hour < 11 ? '早上好' : hour < 13 ? '中午好' : hour < 18 ? '下午好' : '晚上好'
}

function TodoCard({
  icon: Icon,
  iconClass,
  title,
  count,
  empty,
  children,
}: {
  icon: LucideIcon
  iconClass: string
  title: string
  count: number
  empty: string
  children: ReactNode
}) {
  return (
    <Card className={styles.todo}>
      <div className={styles.todoHead}>
        <span className={cx(styles.icon, iconClass)}>
          <Icon size={16} aria-hidden />
        </span>
        <h3>{title}</h3>
        <span className={styles.count}>{count}</span>
      </div>
      {count > 0 ? (
        <ul className={styles.rows}>{children}</ul>
      ) : (
        <p className={styles.empty}>{empty}</p>
      )}
    </Card>
  )
}

function Row({
  to,
  title,
  detail,
  before,
  after,
}: {
  to?: string
  title: string
  detail: string
  before?: ReactNode
  after?: ReactNode
}) {
  const body = (
    <>
      {before}
      <span className={styles.rowText}>
        <strong>{title}</strong>
        <small>{detail}</small>
      </span>
      {after}
      {to && <ChevronRight size={16} aria-hidden />}
    </>
  )
  return (
    <li>
      {to ? (
        <Link to={to} className={styles.row}>
          {body}
        </Link>
      ) : (
        <div className={styles.row}>{body}</div>
      )}
    </li>
  )
}

function NextStep({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action: ReactNode
}) {
  return (
    <Card className={styles.next} style={{ gridTemplateColumns: '1fr' }} aria-label="下一步">
      <div>
        <Chip tone="primary">
          <Flag aria-hidden />
          下一步
        </Chip>
        <h2>{title}</h2>
        <p>{description}</p>
        <div className={styles.actions}>{action}</div>
      </div>
    </Card>
  )
}

const papersOf = (group: PracticeGroup) =>
  [...new Set(group.items.map((item) => paperName(item.paper_title)))].join('、')

export function HomePage() {
  const { data: practices } = usePractices('topic')
  const { data: tasks } = useTasks()
  const { data: papers } = usePapers('0')
  const openOnboarding = useOpenOnboarding()
  const now = new Date()

  const pendingGroups = (practices?.items ?? [])
    .map((group) => ({ group, items: group.items.filter((item) => item.status === 'pending') }))
    .filter((entry) => entry.items.length > 0)
  const grading = (practices?.items ?? [])
    .flatMap((group) => group.items.map((item) => ({ item, group })))
    .filter(({ item }) => item.status === 'grading')
  const gradingUnique = [...new Map(grading.map((entry) => [entry.item.id, entry])).values()]
  const unavailable = tasks?.availability.status === 'unavailable'

  return (
    <>
      <PageHeader
        eyebrow={`${now.getMonth() + 1}月${now.getDate()}日 · 星期${weekdays[now.getDay()]}`}
        title={`${greeting(now)}，先从最要紧的一件开始`}
      />

      {unavailable ? (
        <NextStep
          title="先准备好 AI 服务"
          description="做题龙需要 Codex 才能分析试卷、批改作答。已保存的内容仍然可以查看，完成准备后会自动继续。"
          action={
            <Button variant="primary" size="lg" onClick={openOnboarding}>
              查看准备步骤 <ArrowRight size={16} aria-hidden />
            </Button>
          }
        />
      ) : (
        papers?.total === 0 && (
          <NextStep
            title="上传第一份做过的试卷"
            description="黑笔为考试作答，红笔为事后批改。做题龙会逐题分析，再针对薄弱考点挑选练习。"
            action={
              <ButtonLink variant="primary" size="lg" to="/papers">
                去上传 <ArrowRight size={16} aria-hidden />
              </ButtonLink>
            }
          />
        )
      )}

      <div className={styles.sectionHead}>
        <h2>待办</h2>
        <span>完成后会自动从这里消失</span>
      </div>
      <div className={styles.todoGrid}>
        <TodoCard
          icon={PencilLine}
          iconClass={styles.iconProgress}
          title="待做练习"
          count={practices?.counts.pending ?? 0}
          empty="练习都做完了"
        >
          {pendingGroups.map(({ group, items }) => (
            <Row
              key={group.id}
              to={`/practice?item=${items[0].id}`}
              title={group.label}
              detail={`来自${papersOf(group)}`}
              after={<span className={styles.amount}>{items.length} 道</span>}
            />
          ))}
        </TodoCard>
        <TodoCard
          icon={Clock}
          iconClass={styles.iconProgress}
          title="批改中"
          count={practices?.counts.grading ?? 0}
          empty="没有正在批改的练习"
        >
          {gradingUnique.map(({ item, group }) => (
            <Row
              key={item.id}
              to={`/practice?item=${item.id}`}
              title={group.label}
              detail="一般 1～2 分钟出结果"
              before={<span className={styles.spinner} aria-hidden />}
            />
          ))}
        </TodoCard>
        <TodoCard
          icon={LoaderCircle}
          iconClass={styles.iconProgress}
          title="后台进度"
          count={(tasks?.active ? 1 : 0) + (tasks?.queued_count ?? 0)}
          empty={
            unavailable ? '准备好 AI 服务后，分析和批改会自动进行' : '现在没有进行中的分析或批改'
          }
        >
          {tasks?.active && (
            <Row
              title={`做题龙${tasks.active.progress.message}`}
              detail={
                tasks.queued_count
                  ? `还有 ${tasks.queued_count} 项在等待`
                  : '完成后结果会出现在对应页面'
              }
              before={<span className={styles.spinner} aria-hidden />}
            />
          )}
          {!tasks?.active && tasks && tasks.queued_count > 0 && (
            <Row title={`${tasks.queued_count} 项在等待`} detail="会按顺序自动进行" />
          )}
        </TodoCard>
      </div>
    </>
  )
}
