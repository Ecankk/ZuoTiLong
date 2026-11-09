import { useParams } from 'react-router'
import { endpoints } from '../../api/endpoints'
import { useAction, usePaper, usePaperSummary, useTasks } from '../../api/queries'
import type { PaperSummaryResponse } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { ErrorState } from '../../components/ui/ErrorState'
import { Skeleton } from '../../components/ui/Skeleton'
import { friendlyError } from '../../lib/errors'
import styles from './PaperOverview.module.css'

type Item = string | { text: string }
const text = (item: Item) => (typeof item === 'string' ? item : item.text)

function Section({ title, items }: { title: string; items?: Item[] }) {
  if (!items?.length) return null
  return (
    <Card padded className={styles.card}>
      <h2>{title}</h2>
      <ul className={styles.list}>
        {items.map((item, index) => (
          <li key={index}>
            <MathText text={text(item)} />
          </li>
        ))}
      </ul>
    </Card>
  )
}

function SummaryBody({ summary }: { summary: NonNullable<PaperSummaryResponse['summary']> }) {
  return (
    <>
      {summary.overview && (
        <Card padded className={styles.card}>
          <h2>概述</h2>
          <p className="read">
            <MathText text={summary.overview} />
          </p>
        </Card>
      )}
      <Section title="主要发现" items={summary.key_findings} />
      <Section title="已有改善" items={summary.improvements} />
      <Section title="后续重点" items={summary.next_actions} />
      <Section title="说明" items={summary.limitations} />
    </>
  )
}

export function PaperSummary() {
  const { paperId = '' } = useParams()
  const { data: paper } = usePaper(paperId)
  const { data, error, refetch } = usePaperSummary(paperId)
  const { data: tasks } = useTasks()
  const summarize = useAction(() => endpoints.summarizePaper(paperId), [['papers'], ['tasks']])
  if (!data && error)
    return <ErrorState error={error} title="本卷总结没能读取" onRetry={() => void refetch()} />
  if (!data || !paper) return <Skeleton />
  const archived = Boolean(paper.paper.archived_at)
  const running = tasks?.items.some(
    (t) =>
      t.paper_id === paperId &&
      t.kind === 'summarize_paper' &&
      (t.status === 'running' || t.status === 'queued'),
  )
  const pending = paper.practice_counts.pending
  const action = !archived && !running && (
    <div className={styles.actions}>
      <Button
        variant={data.summary ? 'secondary' : 'primary'}
        disabled={summarize.isPending}
        onClick={() => summarize.mutate(undefined)}
      >
        {data.summary ? '更新本卷总结' : '生成本卷总结'}
      </Button>
    </div>
  )
  const status = running && (
    <div className={styles.status} role="status">
      <span className={styles.spinner} aria-hidden />
      做题龙正在整理本卷总结
    </div>
  )
  const failure = summarize.error && (
    <p className={styles.error}>{friendlyError(summarize.error)}</p>
  )
  // 还没有总结：一张卡片说清总结包含什么，再给生成按钮
  if (!data.summary)
    return (
      <div className={styles.column} style={{ maxWidth: 'var(--read-max)' }}>
        <Card padded className={styles.card}>
          <h2>还没有本卷总结</h2>
          <p>做题龙会汇总这份试卷的逐题分析和练习批改，整理成：</p>
          <ul className={styles.list}>
            <li>主要发现：这份卷子里反复出现的问题</li>
            <li>已有改善：练习里已经做对、补上的地方</li>
            <li>后续重点：接下来最值得花时间的考点</li>
          </ul>
          {pending > 0 && !archived && (
            <p className={styles.muted} style={{ marginTop: 'var(--space-3)' }}>
              本卷还有 {pending} 道练习没做，建议做完后再生成，总结会更完整。
            </p>
          )}
          {status}
          {action}
          {failure}
        </Card>
      </div>
    )
  return (
    <div className={styles.column} style={{ maxWidth: 'var(--read-max)' }}>
      <SummaryBody summary={data.summary} />
      <Card padded className={styles.card}>
        <p className={styles.muted}>总结会随着练习批改变化。做完一部分练习后，可以更新一次。</p>
        {status}
        {action}
        {failure}
      </Card>
    </div>
  )
}
