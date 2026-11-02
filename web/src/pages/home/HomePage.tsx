import {
  ArrowRight,
  Check,
  ChevronRight,
  CircleHelp,
  Clock,
  FileText,
  Flag,
  PencilLine,
  Target,
  type LucideIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useHome } from '../../api/queries'
import type { HomeData } from '../../api/types'
import { ButtonLink } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip, CorrectnessChip } from '../../components/ui/Chip'
import { PaperPlaceholder } from '../../components/ui/PaperPlaceholder'
import { PageHeader } from '../../components/ui/PageHeader'
import { cx } from '../../lib/cx'
import { assessmentCorrectness, paperName } from '../../lib/labels'
import styles from './HomePage.module.css'

const weekdays = ['日', '一', '二', '三', '四', '五', '六']

function greeting(date: Date) {
  const hour = date.getHours()
  return hour < 11 ? '早上好' : hour < 13 ? '中午好' : hour < 18 ? '下午好' : '晚上好'
}

function minutesAgo(iso: string, now: Date) {
  const minutes = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60000))
  return minutes < 1 ? '刚刚提交' : `${minutes} 分钟前提交`
}

function TodoCard({
  icon: Icon,
  iconClass,
  title,
  count,
  hint,
  empty,
  children,
}: {
  icon: LucideIcon
  iconClass: string
  title: string
  count: number
  hint?: string
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
        {hint && <span className={styles.hint}>{hint}</span>}
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

function NextStep({ step }: { step: NonNullable<HomeData['next_step']> }) {
  return (
    <Card className={styles.next} aria-label="下一步">
      <div>
        <Chip tone="primary">
          <Flag aria-hidden />
          下一步
        </Chip>
        <h2>{step.title}</h2>
        <p>{step.description}</p>
        <div className={styles.actions}>
          <ButtonLink variant="primary" size="lg" to={step.to}>
            {step.action_label} <ArrowRight size={16} aria-hidden />
          </ButtonLink>
        </div>
      </div>
      {step.preview_caption && (
        <div className={styles.preview} aria-hidden>
          <span className={styles.previewCaption}>{step.preview_caption}</span>
          <PaperPlaceholder
            className={styles.previewPaper}
            lines={[['p', 92], ['p', 78], ['p', 85], ['gap'], ['h', 30]]}
          />
          <span className={styles.unclear} />
        </div>
      )}
    </Card>
  )
}

const suggestionIcon = {
  repeated_errors: Target,
  no_practice: FileText,
  unfinished_practice: PencilLine,
}
const suggestionKind = {
  repeated_errors: '连续出错',
  no_practice: '还没有练习',
  unfinished_practice: '未做练习',
}

export function HomePage() {
  const { data } = useHome()
  if (!data) return null
  const now = new Date()
  const { todos } = data
  return (
    <>
      <PageHeader
        eyebrow={`${now.getMonth() + 1}月${now.getDate()}日 · 星期${weekdays[now.getDay()]}`}
        title={`${greeting(now)}，先从最要紧的一件开始`}
        actions={
          <div className={styles.stats}>
            <div className={styles.stat}>
              <b>{data.stats.weekly_practice_done}</b>
              <span>本周完成练习</span>
            </div>
            <div className={styles.stat}>
              <b>{Math.round(data.stats.independent_accuracy * 100)}%</b>
              <span>练习独立正确率</span>
            </div>
            <div className={styles.stat}>
              <b>{data.stats.analyzed_papers}</b>
              <span>已分析试卷</span>
            </div>
          </div>
        }
      />

      {data.next_step && <NextStep step={data.next_step} />}

      <div className={styles.sectionHead}>
        <h2>待办</h2>
        <span>完成后会自动从这里消失</span>
      </div>
      <div className={styles.todoGrid}>
        <TodoCard
          icon={CircleHelp}
          iconClass={styles.iconReview}
          title="待核对的题"
          count={todos.review.length}
          hint="核对后才能生成练习"
          empty="没有需要核对的题"
        >
          {todos.review.map((item) => (
            <Row
              key={`${item.paper_id}-${item.question_number}`}
              to={`/papers/${item.paper_id}/questions/${item.question_number}`}
              title={`${paperName(item.paper_title)}第 ${item.question_number} 题`}
              detail={item.reason}
            />
          ))}
        </TodoCard>

        <TodoCard
          icon={PencilLine}
          iconClass={styles.iconProgress}
          title="待做练习"
          count={todos.practice.reduce((sum, item) => sum + item.remaining, 0)}
          hint="按考点"
          empty="练习都做完了"
        >
          {todos.practice.map((item) => (
            <Row
              key={item.topic.topic_id}
              to={`/practice?item=${item.practice_id}`}
              title={item.topic.name}
              detail={`来自${paperName(item.paper_title)}第 ${item.question_number} 题`}
              after={<span className={styles.amount}>{item.remaining} 道</span>}
            />
          ))}
        </TodoCard>

        <TodoCard
          icon={Clock}
          iconClass={styles.iconProgress}
          title="批改中"
          count={todos.grading.length}
          empty="没有正在批改的练习"
        >
          {todos.grading.map((item) => (
            <Row
              key={item.practice_id}
              title={item.label}
              detail={`${minutesAgo(item.submitted_at, now)} · 一般 1～2 分钟出结果`}
              before={<span className={styles.spinner} aria-hidden />}
            />
          ))}
        </TodoCard>

        <TodoCard
          icon={Check}
          iconClass={styles.iconFeedback}
          title="新的批改反馈"
          count={todos.feedback.length}
          empty="暂时没有新的批改反馈"
        >
          {todos.feedback.map((item) => (
            <Row
              key={item.practice_id}
              to={`/practice?item=${item.practice_id}`}
              title={item.label}
              detail={item.summary}
              before={<span className={styles.newDot} aria-label="未读" />}
              after={<CorrectnessChip value={assessmentCorrectness(item.correct)} />}
            />
          ))}
        </TodoCard>
      </div>

      {data.suggestions.length > 0 && (
        <>
          <div className={styles.sectionHead}>
            <h2>建议</h2>
            <span>根据你的做题记录整理</span>
          </div>
          <div className={styles.suggestGrid}>
            {data.suggestions.map((item) => {
              const Icon = suggestionIcon[item.kind]
              return (
                <Card key={item.id} className={styles.suggest}>
                  <span className={cx(styles.kind, item.kind === 'repeated_errors' && styles.warn)}>
                    <Icon size={14} aria-hidden />
                    {suggestionKind[item.kind]}
                  </span>
                  <h3>{item.title}</h3>
                  <p>{item.detail}</p>
                  <ButtonLink size="sm" to={item.to}>
                    {item.action_label}
                  </ButtonLink>
                </Card>
              )
            })}
          </div>
        </>
      )}
    </>
  )
}
