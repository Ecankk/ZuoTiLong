import * as Dialog from '@radix-ui/react-dialog'
import { useMemo, useState } from 'react'
import { ApiError } from '../../api/client'
import { endpoints } from '../../api/endpoints'
import { useAction, usePaperQuestions, useTasks } from '../../api/queries'
import type { QuestionSummary } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { cx } from '../../lib/cx'
import styles from './CorrectNumbers.module.css'

type Action = 'keep' | 'merge' | 'delete'
type Row = { question: QuestionSummary; number: string; action: Action }

const byNumber = (a: QuestionSummary, b: QuestionSummary) => Number(a.number) - Number(b.number)

/** 把每行的选择换成接口需要的分组：并入上一题的行归到前一个保留的题。 */
export function buildCorrection(rows: Row[]) {
  const groups: { number: string; question_ids: string[] }[] = []
  const deleted: string[] = []
  for (const row of rows) {
    if (row.action === 'delete') deleted.push(row.question.id)
    else if (row.action === 'merge' && groups.length > 0)
      groups[groups.length - 1].question_ids.push(row.question.id)
    else groups.push({ number: row.number.trim(), question_ids: [row.question.id] })
  }
  const numbers = groups.map((group) => group.number)
  const problem = numbers.some((n) => !n)
    ? '每道题都需要题号'
    : new Set(numbers).size !== numbers.length
      ? '题号有重复，请检查'
      : groups.length === 0
        ? '至少保留一道题'
        : null
  return { groups, deleted, problem }
}

function friendlyError(error: Error) {
  if (error instanceof ApiError && error.status === 409)
    return '这份试卷已经开始分析、有练习记录或还有任务在进行，不能再纠正题号了。'
  return error.message
}

function Editor({
  paperId,
  questions,
  onDone,
}: {
  paperId: string
  questions: QuestionSummary[]
  onDone: () => void
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    [...questions]
      .sort(byNumber)
      .map((question) => ({ question, number: question.number, action: 'keep' })),
  )
  const [confirming, setConfirming] = useState(false)
  const { data: tasks } = useTasks()
  const { groups, deleted, problem } = useMemo(() => buildCorrection(rows), [rows])
  const correct = useAction(
    () => endpoints.correctQuestions(paperId, groups, deleted),
    [['questions'], ['papers']],
  )
  const cancelTask = useAction(
    (jobId: string) => endpoints.taskAction(jobId, 'cancel'),
    [['tasks'], ['papers']],
  )
  const pendingAnalysis = tasks?.items.find(
    (task) =>
      task.paper_id === paperId &&
      task.status === 'queued' &&
      task.allowed_actions.includes('cancel'),
  )
  const update = (index: number, change: Partial<Row>) =>
    setRows((before) => before.map((row, i) => (i === index ? { ...row, ...change } : row)))
  const merged = rows.filter((row) => row.action === 'merge').length

  if (confirming)
    return (
      <>
        <p className={styles.text}>
          纠正后共 {groups.length} 道题
          {merged > 0 && `，其中合并了 ${merged} 个碎片`}
          {deleted.length > 0 && `，删除 ${deleted.length} 个误切的题`}。
        </p>
        <p className={styles.text}>做题龙会保存原来的切分，纠正后按新的题号分析。</p>
        {correct.error && <p className={styles.error}>{friendlyError(correct.error)}</p>}
        <div className={styles.actions}>
          <Button disabled={correct.isPending} onClick={() => setConfirming(false)}>
            返回修改
          </Button>
          <Button
            variant="primary"
            disabled={correct.isPending}
            onClick={() => correct.mutate(undefined, { onSuccess: onDone })}
          >
            {correct.isPending ? '正在保存…' : '确认纠正'}
          </Button>
        </div>
      </>
    )

  return (
    <>
      <p className={styles.text}>
        可以改题号、把被切开的碎片并入上一题，或删除不是题目的部分。一道题被合在一起的情况暂不支持拆开。
      </p>
      {pendingAnalysis && (
        <div className={styles.notice}>
          <span>这份试卷的分析正在排队，需要先取消排队才能纠正题号。纠正后可以重新开始分析。</span>
          <Button
            size="sm"
            disabled={cancelTask.isPending}
            onClick={() => cancelTask.mutate(pendingAnalysis.id)}
          >
            取消排队中的分析
          </Button>
        </div>
      )}
      <ol className={styles.rows}>
        {rows.map((row, index) => (
          <li
            key={row.question.id}
            className={cx(styles.row, row.action !== 'keep' && styles[row.action])}
          >
            <img
              className={styles.crop}
              src={`/api/questions/${encodeURIComponent(row.question.id)}/evidence?region=0`}
              alt={`原第 ${row.question.number} 题切图`}
              loading="lazy"
            />
            <label className={styles.numberField}>
              题号
              <input
                value={row.action === 'keep' ? row.number : ''}
                disabled={row.action !== 'keep'}
                placeholder={
                  row.action === 'merge' ? '并入上一题' : row.action === 'delete' ? '删除' : ''
                }
                onChange={(event) => update(index, { number: event.target.value })}
              />
            </label>
            <select
              aria-label={`原第 ${row.question.number} 题的处理`}
              value={row.action}
              onChange={(event) => update(index, { action: event.target.value as Action })}
            >
              <option value="keep">作为一道题</option>
              {index > 0 && <option value="merge">并入上一题</option>}
              <option value="delete">删除（不是题目）</option>
            </select>
          </li>
        ))}
      </ol>
      {problem && <p className={styles.error}>{problem}</p>}
      <div className={styles.actions}>
        <Dialog.Close asChild>
          <Button>取消</Button>
        </Dialog.Close>
        <Button variant="primary" disabled={Boolean(problem)} onClick={() => setConfirming(true)}>
          下一步
        </Button>
      </div>
    </>
  )
}

/** 分析开始前纠正切分：重新编号、合并碎片、删除误切的题。 */
export function CorrectNumbersButton({ paperId }: { paperId: string }) {
  const [open, setOpen] = useState(false)
  const { data } = usePaperQuestions(paperId)
  if (!data?.items.length) return null
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button size="sm">纠正题号</Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.dialog} aria-describedby={undefined}>
          <Dialog.Title className={styles.title}>纠正题号</Dialog.Title>
          {open && (
            <Editor paperId={paperId} questions={data.items} onDone={() => setOpen(false)} />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
