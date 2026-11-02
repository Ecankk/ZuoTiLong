import { Navigate, Outlet, useParams } from 'react-router'
import { usePaper, usePaperQuestions } from '../../api/queries'
import { PageHeader } from '../../components/ui/PageHeader'
import { SegmentedLinks } from '../../components/ui/Segmented'
import { monthDay, paperName } from '../../lib/labels'
import { PlaceholderPage } from '../Placeholder'

export function PaperLayout() {
  const { paperId = '' } = useParams()
  const { data, isPending } = usePaper(paperId)
  if (isPending) return null
  if (!data)
    return (
      <PlaceholderPage
        title="没有找到这份试卷"
        intro="它可能已经归档。可以回到："
        items={['试卷列表']}
      />
    )
  const { paper } = data
  return (
    <>
      <PageHeader
        crumbs={[{ label: '试卷', to: '/papers' }, { label: paperName(paper.title) }]}
        title={paperName(paper.title)}
        subtitle={
          <span className="tabular">
            {paper.exam_date ? `${monthDay(paper.exam_date)}作答` : '作答日期未填'}
            {paper.score !== null && ` · 得分 ${paper.score} / ${paper.total_score}`}
          </span>
        }
        actions={
          <SegmentedLinks
            label="试卷内容"
            links={[
              { to: `/papers/${paper.id}`, label: '概览', end: true },
              { to: `/papers/${paper.id}/questions`, label: '逐题分析' },
              { to: `/papers/${paper.id}/summary`, label: '本卷总结' },
            ]}
          />
        }
      />
      <Outlet />
    </>
  )
}

/** 进入逐题分析时，先看第一道有误的题；没有错题则从第一题开始。 */
export function FirstQuestionRedirect() {
  const { paperId = '' } = useParams()
  const { data } = usePaperQuestions(paperId)
  if (!data) return null
  const first = data.items.find((question) => question.correctness === 'wrong') ?? data.items[0]
  if (!first)
    return <PlaceholderPage header={<></>} title="" intro="这份试卷还没有定位到题目。" items={[]} />
  return <Navigate replace to={`/papers/${paperId}/questions/${first.number}`} />
}

export const PaperOverview = () => (
  <PlaceholderPage
    header={<></>}
    title="概览"
    intro="这里将展示本卷概览："
    items={['得分与正误分布', '本卷薄弱考点，可直接进入对应练习']}
  />
)

export const PaperSummary = () => (
  <PlaceholderPage
    header={<></>}
    title="本卷总结"
    intro="完成本卷练习后，这里会汇总："
    items={['主要发现', '已有改善', '后续重点']}
  />
)
