import { Archive, ArchiveRestore } from 'lucide-react'
import { useState } from 'react'
import { Navigate, Outlet, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { endpoints } from '../../api/endpoints'
import { useAction, usePaper, usePaperQuestions } from '../../api/queries'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { ErrorState } from '../../components/ui/ErrorState'
import { PageHeader } from '../../components/ui/PageHeader'
import { SegmentedLinks } from '../../components/ui/Segmented'
import { Skeleton } from '../../components/ui/Skeleton'
import { monthDay, paperName } from '../../lib/labels'
import { PlaceholderPage } from '../Placeholder'
import styles from './PaperOverview.module.css'

function ArchiveButton({ paperId, archived }: { paperId: string; archived: boolean }) {
  const [open, setOpen] = useState(false)
  const action = useAction(
    () => (archived ? endpoints.restorePaper(paperId) : endpoints.archivePaper(paperId)),
    [['papers'], ['practices'], ['questions']],
  )
  return (
    <>
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
        error={action.error?.message}
        onConfirm={() => action.mutate(undefined, { onSuccess: () => setOpen(false) })}
      >
        {archived
          ? '恢复后，这份试卷和它的练习会重新计入画像和待办。'
          : '归档后，这份试卷和它的练习不再计入画像和待办。原卷、分析和作答都会保留，之后可以恢复。'}
      </ConfirmDialog>
    </>
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
            {paper.exam_date ? `${monthDay(paper.exam_date)}作答` : '作答日期未填'}
            {paper.score !== null && ` · 得分 ${paper.score} / ${paper.total_score}`}
            {archived && ' · 已归档'}
          </span>
        }
        actions={
          <div className={styles.headerActions}>
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
