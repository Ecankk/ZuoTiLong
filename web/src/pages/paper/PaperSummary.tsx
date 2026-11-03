import { useParams } from 'react-router'
import { endpoints } from '../../api/endpoints'
import { useAction, usePaper, usePaperSummary, useTasks } from '../../api/queries'
import type { PaperSummaryResponse } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
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
  const { data } = usePaperSummary(paperId)
  const { data: tasks } = useTasks()
  const summarize = useAction(() => endpoints.summarizePaper(paperId), [['papers'], ['tasks']])
  if (!data || !paper) return null
  const archived = Boolean(paper.paper.archived_at)
  const running = tasks?.items.some(
    (t) =>
      t.paper_id === paperId &&
      t.kind === 'summarize_paper' &&
      (t.status === 'running' || t.status === 'queued'),
  )
  return (
    <div className={styles.column} style={{ maxWidth: 'var(--read-max)' }}>
      <Card padded className={styles.card}>
        <h2>本卷总结</h2>
        <p className={styles.muted}>
          汇总这份试卷的逐题分析和练习批改：主要问题、已有改善和后续重点。可以在练习做完一部分后再更新。
        </p>
        {running && (
          <div className={styles.status} role="status">
            <span className={styles.spinner} aria-hidden />
            做题龙正在整理本卷总结
          </div>
        )}
        {!archived && !running && (
          <div className={styles.actions}>
            <Button
              variant="primary"
              disabled={summarize.isPending}
              onClick={() => summarize.mutate(undefined)}
            >
              {data.status === 'available' ? '更新本卷总结' : '生成本卷总结'}
            </Button>
          </div>
        )}
        {summarize.error && <p className={styles.error}>{summarize.error.message}</p>}
      </Card>
      {data.summary ? (
        <SummaryBody summary={data.summary} />
      ) : (
        <Card padded className={styles.card}>
          <p className={styles.muted}>还没有本卷总结。</p>
        </Card>
      )}
    </div>
  )
}
