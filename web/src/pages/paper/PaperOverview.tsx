import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { endpoints } from '../../api/endpoints'
import { useAction, usePaper, usePreferences, useTasks } from '../../api/queries'
import type { Correctness, MathType, PaperResponse, Task } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Button, ButtonLink } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip } from '../../components/ui/Chip'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { cx } from '../../lib/cx'
import { friendlyError } from '../../lib/errors'
import { correctnessLabel, mathTypeName } from '../../lib/labels'
import { awaitingSplitConfirm, ConfirmSplitCard } from './ConfirmSplit'
import styles from './PaperOverview.module.css'

const countOrder: Correctness[] = ['correct', 'partial', 'wrong', 'unknown']
const countColor: Record<Correctness, string> = {
  correct: 'var(--status-correct)',
  partial: 'var(--status-partial)',
  wrong: 'var(--status-wrong)',
  unknown: 'var(--status-unknown)',
}

/** 分析状态与操作：分析、重新分析（需确认）、准备练习。 */
function AnalysisCard({ data }: { data: PaperResponse }) {
  const { paper, analysis } = data
  const { data: tasks } = useTasks()
  const [confirm, setConfirm] = useState(false)
  const hasReport = analysis.report_id !== null
  const analyze = useAction(
    (confirmed: boolean) => endpoints.analyzePaper(paper.id, confirmed),
    [['papers'], ['questions'], ['tasks']],
  )
  const prepare = useAction(() => endpoints.preparePractice(paper.id), [['practices'], ['tasks']])
  // 只看这份试卷的分析任务；选题（准备练习）等其他任务不算“分析”
  const isAnalysis = (t: Task) => t.paper_id === paper.id && t.kind === 'analyze_paper'
  const running = tasks?.active && isAnalysis(tasks.active) ? tasks.active : null
  const queued = tasks?.items.some((t) => isAnalysis(t) && t.status === 'queued')
  const preparing = tasks?.items.some(
    (t) =>
      t.paper_id === paper.id &&
      t.kind === 'prepare_practice' &&
      (t.status === 'queued' || t.status === 'running'),
  )
  const unavailable = tasks?.availability.status === 'unavailable'
  const canAnalyze = data.actions.includes('analyze')

  return (
    <Card padded className={styles.card} aria-label="分析">
      <h2>逐题分析</h2>
      {running ? (
        <div className={styles.status} role="status">
          <span className={styles.spinner} aria-hidden />
          做题龙{running.progress.message}
        </div>
      ) : queued ? (
        <div className={cx(styles.status, unavailable && styles.warn)} role="status">
          {unavailable
            ? '分析已排队。做题龙还不能开始工作，准备好 AI 服务后会自动继续。'
            : '分析已排队，会按顺序自动开始。'}
        </div>
      ) : null}
      {analysis.summary ? (
        <p>
          <MathText text={analysis.summary} />
        </p>
      ) : (
        !running && !queued && <p className={styles.muted}>这份试卷还没有分析结果。</p>
      )}
      {canAnalyze && (
        <div className={styles.actions}>
          {hasReport ? (
            <>
              <Button
                variant="primary"
                disabled={prepare.isPending || preparing}
                onClick={() => prepare.mutate(undefined)}
              >
                为薄弱考点准备练习
              </Button>
              <Button onClick={() => setConfirm(true)}>重新分析</Button>
            </>
          ) : (
            !running &&
            !queued && (
              <Button
                variant="primary"
                disabled={analyze.isPending}
                onClick={() => analyze.mutate(true)}
              >
                开始分析
              </Button>
            )
          )}
        </div>
      )}
      {(prepare.isSuccess || preparing) && (
        <p className={styles.ok}>已开始准备练习，完成后会出现在“练习”里。</p>
      )}
      {(prepare.error || (!confirm && analyze.error)) && (
        <p className={styles.error}>{friendlyError(prepare.error ?? analyze.error)}</p>
      )}
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="重新分析这份试卷？"
        confirmLabel="确认重新分析"
        pending={analyze.isPending}
        error={analyze.error ? friendlyError(analyze.error) : null}
        onConfirm={() => analyze.mutate(true, { onSuccess: () => setConfirm(false) })}
      >
        做题龙会按现在的原卷重新逐题分析，生成新的结果。旧的分析和你的作答都会保留。
      </ConfirmDialog>
    </Card>
  )
}

function ScoreCard({ data }: { data: PaperResponse }) {
  const { paper } = data
  const { data: preferences } = usePreferences()
  const [score, setScore] = useState(paper.score === null ? '' : String(paper.score))
  const [total, setTotal] = useState(String(paper.total_score))
  const [mathType, setMathType] = useState<MathType | null>(null)
  const save = useAction(
    () =>
      endpoints.scorePaper(
        paper.id,
        Number(score),
        Number(total),
        mathType ?? preferences?.study_type ?? 1,
      ),
    [['papers']],
  )
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate(undefined)
  }
  return (
    <Card padded className={styles.card} aria-label="总分">
      <h2>总分</h2>
      <p className={styles.score}>
        {paper.score !== null ? (
          <>
            <b>{paper.score}</b> / {paper.total_score} 分
          </>
        ) : (
          <span className={styles.muted}>
            还没有核定。按阅卷结果填写，画像里的成绩趋势只用核定分数。
          </span>
        )}
      </p>
      <form className={styles.form} onSubmit={submit}>
        <label className={styles.field}>
          得分
          <input
            type="number"
            min="0"
            step="any"
            required
            value={score}
            onChange={(event) => setScore(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          满分
          <input
            type="number"
            min="1"
            required
            value={total}
            onChange={(event) => setTotal(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          类别
          <select
            value={mathType ?? preferences?.study_type ?? 1}
            onChange={(event) => setMathType(Number(event.target.value) as MathType)}
          >
            {([1, 2, 3] as MathType[]).map((type) => (
              <option key={type} value={type}>
                {mathTypeName(type)}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" disabled={save.isPending || score === ''}>
          {paper.score !== null ? '更新总分' : '核定总分'}
        </Button>
      </form>
      {save.isSuccess && <p className={styles.ok}>已保存</p>}
      {save.error && <p className={styles.error}>{friendlyError(save.error)}</p>}
    </Card>
  )
}

/** 原卷没能定位到题目时，让用户填写题目数量建立题号。 */
function NumberCard({ data }: { data: PaperResponse }) {
  const { data: preferences } = usePreferences()
  const [count, setCount] = useState('22')
  const confirm = useAction(() => {
    const numbers = Array.from({ length: Number(count) }, (_, i) => String(i + 1))
    return endpoints.confirmNumbers(
      data.paper.id,
      numbers,
      [],
      mathTypeName(preferences?.study_type ?? 1),
    )
  }, [['papers'], ['questions']])
  return (
    <Card padded className={styles.card} aria-label="确认题号">
      <h2>确认题号</h2>
      <p>做题龙没能从原卷里定位到题目。填写这份试卷的题目数量，会按 1、2、3……建立题号。</p>
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault()
          confirm.mutate(undefined)
        }}
      >
        <label className={styles.field}>
          题目数量
          <input
            type="number"
            min="1"
            max="60"
            required
            value={count}
            onChange={(event) => setCount(event.target.value)}
          />
        </label>
        <Button type="submit" disabled={confirm.isPending}>
          建立题号
        </Button>
      </form>
      {confirm.error && <p className={styles.error}>{friendlyError(confirm.error)}</p>}
    </Card>
  )
}

export function PaperOverview() {
  const { paperId = '' } = useParams()
  const { data } = usePaper(paperId)
  const { data: tasks } = useTasks()
  if (!data) return null
  const { paper } = data
  const { counts } = paper
  const archived = Boolean(paper.archived_at)
  const busy = tasks?.items.some(
    (t) => t.paper_id === paper.id && (t.status === 'running' || t.status === 'queued'),
  )
  const practice = data.practice_counts
  const awaiting = awaitingSplitConfirm(data, tasks?.items)
  return (
    <div className={styles.grid}>
      <div className={styles.column}>
        {archived && (
          <Card padded className={styles.card}>
            <p>这份试卷已归档，可以查看但不能继续分析和练习。需要时点右上角“恢复试卷”。</p>
          </Card>
        )}
        {awaiting ? <ConfirmSplitCard data={data} /> : !archived && <AnalysisCard data={data} />}
        {!archived && counts.total === 0 && !busy && <NumberCard data={data} />}
        {counts.total > 0 && !awaiting && (
          <Card padded className={styles.card} aria-label="正误分布">
            <h2>正误分布</h2>
            <div className={styles.bar} aria-hidden>
              {countOrder.map((key) => (
                <span
                  key={key}
                  style={{
                    width: `${(counts[key] / counts.total) * 100}%`,
                    background: countColor[key],
                  }}
                />
              ))}
            </div>
            <div className={styles.counts}>
              {countOrder
                .filter((key) => counts[key] > 0)
                .map((key) => (
                  <span key={key}>
                    <i style={{ background: countColor[key] }} />
                    {correctnessLabel[key]} {counts[key]}
                  </span>
                ))}
              <span>共 {counts.total} 题</span>
            </div>
            <div className={styles.actions}>
              <ButtonLink size="sm" to={`/papers/${paper.id}/questions`}>
                查看逐题分析
              </ButtonLink>
            </div>
          </Card>
        )}
      </div>
      <div className={styles.column}>
        <ScoreCard data={data} />
        <Card padded className={styles.card} aria-label="薄弱考点">
          <h2>本卷薄弱考点</h2>
          {data.weak_topics.length > 0 ? (
            <div className={styles.tags}>
              {data.weak_topics.map((topic) => (
                <Link
                  key={topic.topic_id}
                  to={`/practice?topic=${encodeURIComponent(topic.topic_id)}`}
                >
                  <Chip tone="primary">{topic.name}</Chip>
                </Link>
              ))}
            </div>
          ) : (
            <p className={styles.muted}>分析完成并关联考点后会显示在这里。</p>
          )}
          <p className={styles.muted} style={{ marginTop: 'var(--space-3)' }}>
            本卷练习：{practice.pending} 道待做
            {practice.grading > 0 && ` · ${practice.grading} 道批改中`}
            {practice.graded > 0 && ` · ${practice.graded} 道已批改`}
          </p>
          {practice.total > 0 && (
            <div className={styles.actions}>
              <ButtonLink size="sm" to="/practice?view=paper">
                去练习
              </ButtonLink>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
