import * as Dialog from '@radix-ui/react-dialog'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError } from '../../api/client'
import { endpoints, requestId } from '../../api/endpoints'
import { queryKeys, useAction } from '../../api/queries'
import type { DuplicateCheck, PaperResponse } from '../../api/types'
import { friendlyError } from '../../lib/errors'
import {
  choiceIncomplete,
  dateUpdateFields,
  examDateLine,
  NO_DATE,
  type DateChoice,
} from '../../lib/examDate'
import { paperName } from '../../lib/labels'
import { Button } from '../ui/Button'
import { ConfirmDialog } from '../ui/ConfirmDialog'
import dialogStyles from '../ui/ConfirmDialog.module.css'
import { ExamDateInput } from './ExamDateInput'
import styles from './PaperDialogs.module.css'

export const MAX_DATE_BATCH = 50

/** 409 的 reason（B28b）→ 学生能看懂的一句话；不认识的 reason 用后端原话 */
const decisionConflict: Record<string, string> = {
  revision_stale: '这份试卷的情况刚刚有变化，已重新读取，请再选一次。',
  has_history: '这份试卷已经有分析或练习记录，不能撤回了；可以选“这是重做”保留它。',
  task_active: '这份试卷还有任务没结束，等它结束后再决定。',
  request_conflict: '这次操作和刚才的操作冲突了，已重新读取，请再选一次。',
  withdrawn: '这份试卷已经撤回了。',
}
const datesConflict: Record<string, string> = {
  task_active: '有试卷正在分析或排队，等它们完成后再改日期。',
  withdrawn: '选中的试卷里有已经撤回的，不能改日期。',
  request_conflict: '这次修改和刚才的操作冲突了，请关掉后重新打开再改。',
  revision_stale: '试卷的情况刚刚有变化，请关掉后重新打开再改。',
}
const conflictText = (error: unknown, table: Record<string, string>, fallback: string) =>
  error instanceof ApiError && error.status === 409
    ? ((error.reason && table[error.reason]) ?? fallback)
    : friendlyError(error)
const dateKeys = [['papers'], ['profile']]

/** 修改作答日期（单份或多选批量，一次最多 50 份） */
export function EditDatesDialog({
  paperIds,
  initial = NO_DATE,
  open,
  onOpenChange,
  onDone,
}: {
  paperIds: string[]
  initial?: DateChoice
  open: boolean
  onOpenChange: (open: boolean) => void
  onDone?: () => void
}) {
  const [choice, setChoice] = useState<DateChoice>(initial)
  const [prevOpen, setPrevOpen] = useState(open)
  // 每次打开都从当前值开始，不沿用上次没提交的选择
  if (open !== prevOpen) {
    setPrevOpen(open)
    if (open) setChoice(initial)
  }
  const save = useAction(
    () =>
      endpoints.updatePaperDates({
        confirmed: true,
        request_id: requestId(),
        paper_ids: paperIds,
        ...dateUpdateFields(choice),
      }),
    dateKeys,
  )
  const incomplete = choiceIncomplete(choice)
  const tooMany = paperIds.length > MAX_DATE_BATCH
  const error = save.error
    ? conflictText(save.error, datesConflict, '有试卷正在分析或排队，等它们完成后再改日期。')
    : null
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) save.reset()
        onOpenChange(next)
      }}
      title={paperIds.length > 1 ? `修改 ${paperIds.length} 份试卷的作答日期` : '修改作答日期'}
      confirmLabel="保存日期"
      pending={save.isPending}
      error={error}
      onConfirm={() => {
        if (incomplete || tooMany) return
        save.mutate(undefined, {
          onSuccess: () => {
            onOpenChange(false)
            onDone?.()
          },
        })
      }}
    >
      <div className={styles.dateBody}>
        <ExamDateInput value={choice} onChange={setChoice} noneLabel="不填（日期未知）" />
        {incomplete && (
          <p className={styles.hint}>
            {choice.mode === 'day' ? '请选哪一天。' : '请选大约哪个月。'}
          </p>
        )}
        {tooMany && <p className={styles.warn}>一次最多改 {MAX_DATE_BATCH} 份，请少选一些。</p>}
        <p className={styles.note}>
          旧版本上传的试卷，作答日期可能被自动填成了上传当天，建议核对一下。日期会影响“近期”和每周统计。
        </p>
      </div>
    </ConfirmDialog>
  )
}

/** 已有的同卷摘要 */
function MatchList({ check }: { check: DuplicateCheck }) {
  return (
    <ul className={styles.matches} aria-label="已有的同一份卷">
      {check.matches.map((match) => (
        <li key={match.paper_id}>
          <strong>{paperName(match.title)}</strong>
          <span>
            {examDateLine(match)}
            {' · '}
            {match.has_report ? '已分析' : '还没分析'}
            {match.archived && ' · 已归档'}
          </span>
        </li>
      ))}
    </ul>
  )
}

/**
 * 同一年同一卷又传了一份：这是重做，还是传错了？
 * 可以关掉稍后再决定；409（情况有变或已有学习记录）时重读详情再让用户选。
 */
export function DuplicateDecisionDialog({
  paperId,
  check,
  revision,
  open,
  onOpenChange,
  onDecided,
}: {
  paperId: string
  check: DuplicateCheck
  revision: string | null | undefined
  open: boolean
  onOpenChange: (open: boolean) => void
  onDecided?: (decision: 'retake' | 'withdraw') => void
}) {
  const client = useQueryClient()
  // 409 后重读的详情：之后用它的最新 revision 和核查结果（上传结果里的 revision 不会自己更新）
  const [latest, setLatest] = useState<PaperResponse | null>(null)
  // 重读详情期间不能再点，免得又拿旧 revision 提交一次
  const [refreshing, setRefreshing] = useState(false)
  const currentCheck = latest?.duplicate_check ?? check
  const currentRevision = latest ? latest.decision_revision : revision
  const settled = latest !== null && latest.paper.import_decision !== 'pending_duplicate'
  const decide = useAction(
    (decision: 'retake' | 'withdraw') =>
      endpoints.importDecision(paperId, {
        confirmed: true,
        request_id: requestId(),
        decision,
        decision_revision: currentRevision ?? '',
      }),
    [['papers'], ['profile'], ['tasks']],
  )
  const run = (decision: 'retake' | 'withdraw') => {
    decide.mutate(decision, {
      onSuccess: () => {
        onOpenChange(false)
        onDecided?.(decision)
      },
      onError: (error) => {
        if (error instanceof ApiError && error.status === 409) {
          setRefreshing(true)
          void client
            .fetchQuery({
              queryKey: queryKeys.paper(paperId),
              queryFn: () => endpoints.paper(paperId),
              staleTime: 0,
            })
            .then((fresh) => fresh && setLatest(fresh))
            .catch(() => undefined)
            .finally(() => setRefreshing(false))
          void client.invalidateQueries({ queryKey: ['papers', 'list'] })
        }
      },
    })
  }
  const message = settled
    ? latest.paper.import_decision === 'withdrawn'
      ? '这份试卷已经撤回了。'
      : '这份试卷已经确定是重做，不用再选了。'
    : decide.error
      ? refreshing
        ? '情况有变化，正在重新读取…'
        : conflictText(decide.error, decisionConflict, '这份试卷的情况刚刚有变化，请刷新后再试。')
      : null
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) decide.reset()
        onOpenChange(next)
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className={dialogStyles.overlay} />
        <Dialog.Content className={dialogStyles.dialog} aria-describedby={undefined}>
          <Dialog.Title className={dialogStyles.title}>这份卷之前传过</Dialog.Title>
          <div className={dialogStyles.body}>
            <p>
              {currentCheck.identity
                ? `你已经有一份 ${currentCheck.identity.exam_year} 年数学${'一二三'[currentCheck.identity.math_type - 1]}：`
                : '你已经有一份同年同卷：'}
            </p>
            <MatchList check={currentCheck} />
            <p className={styles.note}>
              如果是隔一段时间又做了一遍，选“这是重做”，两次都会保留；如果是传错了文件，选“撤回”，这份不会进入试卷列表和画像。
            </p>
          </div>
          {message && <p className={dialogStyles.error}>{message}</p>}
          <div className={styles.decisionActions}>
            <Dialog.Close asChild>
              <Button variant="ghost" disabled={decide.isPending}>
                {settled ? '知道了' : '稍后再决定'}
              </Button>
            </Dialog.Close>
            {!settled && (
              <>
                <Button disabled={decide.isPending || refreshing} onClick={() => run('withdraw')}>
                  传错了，撤回
                </Button>
                <Button
                  variant="primary"
                  disabled={decide.isPending || refreshing}
                  onClick={() => run('retake')}
                >
                  {decide.isPending && decide.variables === 'retake' ? '正在处理…' : '这是重做'}
                </Button>
              </>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
