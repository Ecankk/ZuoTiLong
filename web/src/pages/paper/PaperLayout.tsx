import { Archive, ArchiveRestore, CalendarDays, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Navigate, Outlet, useNavigate, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { endpoints } from '../../api/endpoints'
import { useAction, usePaper, usePaperQuestions } from '../../api/queries'
import type { Paper, PaperResponse } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { ErrorState } from '../../components/ui/ErrorState'
import { DuplicateDecisionDialog, EditDatesDialog } from '../../components/paper/PaperDialogs'
import { PageHeader } from '../../components/ui/PageHeader'
import { SegmentedLinks } from '../../components/ui/Segmented'
import { Skeleton } from '../../components/ui/Skeleton'
import { friendlyError } from '../../lib/errors'
import { choiceFrom, examDateLine } from '../../lib/examDate'
import { paperName } from '../../lib/labels'
import { PlaceholderPage } from '../Placeholder'
import styles from './PaperOverview.module.css'

const UNDO_MS = 5000
const archiveKeys = [['papers'], ['practices'], ['questions']]

/** 归档成功后在底部停留 5 秒的提示，可以撤销（调用恢复接口） */
function UndoToast({ paperId, onClose }: { paperId: string; onClose: () => void }) {
  const undo = useAction(() => endpoints.restorePaper(paperId), archiveKeys)
  // 撤销进行中或失败时不自动消失，失败原因要让用户看到
  const holding = undo.isPending || undo.isError
  useEffect(() => {
    if (holding) return
    const timer = window.setTimeout(onClose, UNDO_MS)
    return () => window.clearTimeout(timer)
  }, [holding, onClose])
  return (
    <div className={styles.toast} role="status">
      <span>{undo.isError ? `没能撤销：${friendlyError(undo.error)}` : '已归档这份试卷'}</span>
      {!undo.isError && (
        <button
          type="button"
          disabled={undo.isPending}
          onClick={() => undo.mutate(undefined, { onSuccess: onClose })}
        >
          {undo.isPending ? '正在撤销…' : '撤销'}
        </button>
      )}
      <button type="button" className={styles.toastClose} onClick={onClose} aria-label="关闭提示">
        <X size={16} aria-hidden />
      </button>
    </div>
  )
}

function ArchiveButton({ paperId, archived }: { paperId: string; archived: boolean }) {
  const [open, setOpen] = useState(false)
  const [undoable, setUndoable] = useState(false)
  const closeToast = useCallback(() => setUndoable(false), [])
  const action = useAction(
    () => (archived ? endpoints.restorePaper(paperId) : endpoints.archivePaper(paperId)),
    archiveKeys,
  )
  return (
    <>
      {undoable && <UndoToast paperId={paperId} onClose={closeToast} />}
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        {archived ? <ArchiveRestore size={16} aria-hidden /> : <Archive size={16} aria-hidden />}
        {archived ? '恢复试卷' : '归档'}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={archived ? '恢复这份试卷？' : '归档这份试卷？'}
        confirmLabel={archived ? '确认恢复' : '确认归档'}
        pending={action.isPending}
        error={action.error ? friendlyError(action.error) : null}
        onConfirm={() =>
          action.mutate(undefined, {
            onSuccess: () => {
              setOpen(false)
              setUndoable(!archived)
            },
          })
        }
      >
        {archived
          ? '恢复后，这份试卷和它的练习会重新计入画像和待办。'
          : '归档后，这份试卷和它的练习不再计入画像和待办。原卷、分析和作答都会保留，之后可以恢复。'}
      </ConfirmDialog>
    </>
  )
}

function DateButton({ paper }: { paper: Paper }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        <CalendarDays size={16} aria-hidden />
        改日期
      </Button>
      <EditDatesDialog
        paperIds={[paper.id]}
        initial={choiceFrom(paper)}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  )
}

/** 同卷重复上传还没决定：每个分页上方都提示，可以随时决定 */
function DuplicateNotice({ data }: { data: PaperResponse }) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const check = data.duplicate_check
  if (data.paper.import_decision !== 'pending_duplicate') return null
  return (
    <div className={styles.duplicate} role="region" aria-label="这份卷之前传过">
      <div>
        <strong>这份卷之前传过同一年同一卷</strong>
        <span>先确认是重做还是传错了，确认前不会开始分析，题号可以先看。</span>
      </div>
      {check && check.status === 'same_exam_identity' && (
        <>
          <Button size="sm" variant="primary" onClick={() => setOpen(true)}>
            去决定
          </Button>
          <DuplicateDecisionDialog
            paperId={data.paper.id}
            check={check}
            revision={data.decision_revision}
            open={open}
            onOpenChange={setOpen}
            onDecided={(decision) => decision === 'withdraw' && navigate('/papers')}
          />
        </>
      )}
    </div>
  )
}

export function PaperLayout() {
  const { paperId = '' } = useParams()
  const { data, isPending, error, refetch } = usePaper(paperId)
  if (isPending)
    return (
      <>
        <PageHeader crumbs={[{ label: '试卷', to: '/papers' }]} title="正在读取试卷…" />
        <Skeleton />
      </>
    )
  if (!data && !(error instanceof ApiError && error.status === 404))
    return (
      <>
        <PageHeader crumbs={[{ label: '试卷', to: '/papers' }]} title="试卷" />
        <ErrorState
          error={error}
          title="这份试卷没能读取"
          onRetry={() => void refetch()}
          back={{ to: '/papers', label: '回到试卷列表' }}
        />
      </>
    )
  if (!data)
    return (
      <PlaceholderPage
        title="没有找到这份试卷"
        intro="它可能已经删除。可以回到："
        items={['试卷列表']}
      />
    )
  const { paper } = data
  const archived = Boolean(paper.archived_at)
  return (
    <>
      <PageHeader
        crumbs={[{ label: '试卷', to: '/papers' }, { label: paperName(paper.title) }]}
        title={paperName(paper.title)}
        subtitle={
          <span className="tabular">
            {examDateLine(paper)}
            {paper.score !== null && ` · 得分 ${paper.score} / ${paper.total_score}`}
            {archived && ' · 已归档'}
          </span>
        }
        actions={
          <div className={styles.headerActions}>
            <DateButton paper={paper} />
            <ArchiveButton paperId={paper.id} archived={archived} />
            <SegmentedLinks
              label="试卷内容"
              links={[
                { to: `/papers/${paper.id}`, label: '概览', end: true },
                { to: `/papers/${paper.id}/questions`, label: '逐题分析' },
                { to: `/papers/${paper.id}/summary`, label: '本卷总结' },
              ]}
            />
          </div>
        }
      />
      <DuplicateNotice data={data} />
      <Outlet />
    </>
  )
}

/** 进入逐题分析时，先看第一道有误的题；没有错题则从第一题开始。 */
export function FirstQuestionRedirect() {
  const { paperId = '' } = useParams()
  const { data, error, refetch } = usePaperQuestions(paperId)
  if (!data)
    return error ? (
      <ErrorState error={error} title="题目没能读取" onRetry={() => void refetch()} />
    ) : (
      <Skeleton variant="question" />
    )
  const first = data.items.find((question) => question.correctness === 'wrong') ?? data.items[0]
  if (!first) return <Navigate replace to={`/papers/${paperId}`} />
  return <Navigate replace to={`/papers/${paperId}/questions/${first.number}`} />
}
