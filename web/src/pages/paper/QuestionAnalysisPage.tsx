import { ArrowRight, ChevronLeft, ChevronRight, FileText, ZoomIn } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { usePaperQuestions, useQuestion, useTasks } from '../../api/queries'
import type { QuestionResponse, QuestionSummary, Region, StepComparison } from '../../api/types'
import { ImageViewer, type ViewerTarget } from './ImageViewer'
import { AdjustRegionsButton } from './RegionEditor'
import { MathText } from '../../components/math/MathText'
import { ButtonLink } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { ErrorState } from '../../components/ui/ErrorState'
import { Chip, CorrectnessChip } from '../../components/ui/Chip'
import { Fold } from '../../components/ui/Fold'
import { PaperPlaceholder, type PaperLine } from '../../components/ui/PaperPlaceholder'
import { Skeleton } from '../../components/ui/Skeleton'
import { cx } from '../../lib/cx'
import { QuestionStrip } from './QuestionStrip'
import { ReviewCard } from './ReviewCard'
import styles from './QuestionAnalysisPage.module.css'

type Step = { text: string; mark?: 'error' | 'fix' | 'affected' }

const placeholderLines: PaperLine[] = [
  ['p', 22],
  ['gap'],
  ['p', 96],
  ['p', 70],
  ['gap'],
  ['h', 84],
  ['h', 62],
  ['h', 90],
  ['r', 40, 30],
  ['h', 76],
  ['h', 55],
  ['h', 66],
  ['h', 30],
  ['gap'],
  ['r', 18],
]

function Layer({ index, title }: { index: number; title: string }) {
  return (
    <div className={styles.layer}>
      <span className={styles.layerNumber}>{index}</span>
      {title}
    </div>
  )
}

const markLabel = { error: '首个错误', fix: '改正', affected: '受上一步影响' } as const

function Steps({ steps }: { steps: Step[] }) {
  return (
    <ol className={styles.steps}>
      {steps.map((step, index) => (
        <li key={index} className={cx(styles.step, step.mark && styles[step.mark])}>
          <span className={styles.stepLabel}>
            第 {index + 1} 步{step.mark && ` · ${markLabel[step.mark]}`}
          </span>
          <MathText text={step.text} />
        </li>
      ))}
    </ol>
  )
}

/** 原卷切图；点击打开看图层。读取失败时显示占位，不露出破图。 */
function CropImage({ url, alt, onOpen }: { url: string; alt: string; onOpen: () => void }) {
  const [failed, setFailed] = useState(false)
  if (failed)
    return (
      <PaperPlaceholder
        className={styles.paper}
        lines={placeholderLines}
        caption="原卷切图暂时无法显示"
      />
    )
  return (
    <button type="button" className={styles.cropButton} onClick={onOpen} title="点击放大查看">
      <img className={styles.cropImage} src={url} alt={alt} onError={() => setFailed(true)} />
    </button>
  )
}

function SourcePanel({
  paperId,
  number,
  page,
  images,
  question,
}: {
  paperId: string
  number: string
  page: number | null
  images: string[]
  question?: { id: string; regions: Region[] }
}) {
  const [viewer, setViewer] = useState<ViewerTarget | null>(null)
  // 窄窗口里原卷在分析上方，可以收起
  const [collapsed, setCollapsed] = useState(false)
  return (
    <Card className={cx(styles.source, collapsed && styles.collapsed)} aria-label="原卷">
      <div className={styles.sourceHead}>
        <strong>
          {page ? `原卷第 ${page} 页 · ` : ''}第 {number} 题
        </strong>
        <div className={styles.tools}>
          {question && (
            <AdjustRegionsButton
              paperId={paperId}
              questionId={question.id}
              number={number}
              regions={question.regions}
            />
          )}
          {images[0] && (
            <button
              type="button"
              className={styles.iconButton}
              onClick={() => setViewer({ mode: 'crop', index: 0 })}
              title="放大"
              aria-label="放大查看切图"
            >
              <ZoomIn size={17} aria-hidden />
            </button>
          )}
          {question && question.regions.length > 0 && (
            <button
              type="button"
              className={styles.iconButton}
              onClick={() => setViewer({ mode: 'page', page: page ?? 1 })}
              title="看整页"
              aria-label="查看原卷整页"
            >
              <FileText size={16} aria-hidden />
            </button>
          )}
          <button
            type="button"
            className={styles.collapseToggle}
            aria-expanded={!collapsed}
            onClick={() => setCollapsed(!collapsed)}
          >
            {collapsed ? '展开原卷' : '收起原卷'}
          </button>
        </div>
      </div>
      <div className={styles.sourceBody}>
        {images.length > 0 ? (
          images.map((url, index) => (
            <CropImage
              key={url}
              url={url}
              alt={`第 ${number} 题原卷切图 ${index + 1}`}
              onOpen={() => setViewer({ mode: 'crop', index })}
            />
          ))
        ) : (
          <PaperPlaceholder
            className={styles.paper}
            lines={placeholderLines}
            caption="原卷切图暂不可用"
          />
        )}
        <div className={styles.pens}>
          <span>
            <i className={styles.pen} style={{ background: 'var(--text-regular)' }} />
            黑笔：考试作答
          </span>
          <span>
            <i className={styles.pen} style={{ background: 'var(--status-wrong)' }} />
            红笔：事后批改
          </span>
        </div>
      </div>
      <ImageViewer
        target={viewer}
        onTargetChange={setViewer}
        paperId={paperId}
        number={number}
        crops={images}
        regions={question?.regions ?? []}
      />
    </Card>
  )
}

function Pager({
  paperId,
  questions,
  number,
}: {
  paperId: string
  questions: QuestionSummary[]
  number: string
}) {
  const sorted = [...questions].sort((a, b) => Number(a.number) - Number(b.number))
  const index = sorted.findIndex((question) => question.number === number)
  const previous = sorted[index - 1]
  const next = sorted[index + 1]
  return (
    <div className={styles.pager}>
      {previous ? (
        <ButtonLink variant="ghost" to={`/papers/${paperId}/questions/${previous.number}`}>
          <ChevronLeft size={16} aria-hidden />第 {previous.number} 题
        </ButtonLink>
      ) : (
        <span />
      )}
      {next && (
        <ButtonLink variant="ghost" to={`/papers/${paperId}/questions/${next.number}`}>
          第 {next.number} 题 <ChevronRight size={16} aria-hidden />
        </ButtonLink>
      )}
    </div>
  )
}

const structureLabels: Record<string, string> = {
  conditions: '已知',
  goal: '目标',
  methods: '方法',
}

function structureText(fingerprint: Record<string, unknown> | undefined) {
  return Object.entries(structureLabels)
    .map(([key, label]) => {
      const value = fingerprint?.[key]
      const text = Array.isArray(value) ? value.join('、') : typeof value === 'string' ? value : ''
      return text ? `${label}：${text}` : ''
    })
    .filter(Boolean)
    .join('；')
}

function Comparison({ comparison }: { comparison: StepComparison }) {
  return (
    <>
      <div className={styles.compare}>
        <div>
          <h4>你写的</h4>
          <Steps steps={comparison.yours} />
        </div>
        <div>
          <h4>应该是</h4>
          <Steps steps={comparison.expected} />
        </div>
      </div>
      <p className={styles.why}>
        <b>错在哪：</b>
        <MathText text={comparison.explanation} />
      </p>
    </>
  )
}

/** 没有逐步对照时：本人作答与首个错误并列。 */
function AnswerAndError({ detail }: { detail: QuestionResponse }) {
  const evidence = detail.diagnosis?.answer_evidence
  const error = detail.diagnosis?.first_error
  return (
    <div className={styles.compare}>
      <div>
        <h4>你写的</h4>
        <div className={styles.step}>
          <MathText
            text={
              evidence?.student_state === 'not_attempted'
                ? '这道题没有作答'
                : evidence?.student_work || '作答还没有转写'
            }
          />
        </div>
      </div>
      <div>
        <h4>首个错误</h4>
        <div className={cx(styles.step, error && styles.error)}>
          {error ? (
            <>
              <MathText text={error.step} />
              <span className={styles.stepLabel}>
                <MathText text={error.evidence} />
              </span>
            </>
          ) : (
            '没有找到明确的错误步骤'
          )}
        </div>
      </div>
    </div>
  )
}

function Analysis({ detail }: { detail: QuestionResponse }) {
  const { question, diagnosis } = detail
  const showComparison = question.correctness !== 'correct'
  const guide = diagnosis?.solution_guide
  const causes = diagnosis?.hypotheses ?? []
  const structure = structureText(diagnosis?.fingerprint)
  const practiceCount = detail.practice_counts.total - detail.practice_counts.inactive
  let layer = 1
  return (
    <>
      <Card padded aria-label="结论">
        <Layer index={layer++} title="结论" />
        <div className={styles.verdict}>
          <CorrectnessChip value={question.correctness} />
          <span className={styles.meta}>
            第 {question.number} 题{question.question_type && ` · ${question.question_type}`}
          </span>
          {question.score_earned !== null && question.max_score !== null && (
            <span className={cx(styles.score, question.correctness === 'wrong' && styles.wrong)}>
              <b>{question.score_earned}</b> / {question.max_score} 分
            </span>
          )}
        </div>
        {diagnosis?.observation && (
          <p className={styles.conclusion}>
            <MathText text={diagnosis.observation} />
          </p>
        )}
        <div className={cx('read', styles.stem)}>
          <small className={styles.stemLabel}>题目</small>
          <MathText text={question.stem} />
        </div>
      </Card>

      {showComparison && (
        <Card padded aria-label="作答对照">
          <Layer index={layer++} title="你的作答与首个错误" />
          {detail.capabilities.step_comparison && detail.step_comparison ? (
            <Comparison comparison={detail.step_comparison} />
          ) : (
            <AnswerAndError detail={detail} />
          )}
        </Card>
      )}

      {guide && (
        <Card padded aria-label="解法要点">
          <Layer index={layer++} title="解法要点" />
          <dl className={cx('read', styles.keypoints)}>
            <dt>切入点</dt>
            <dd>
              <MathText text={guide.entry_point} />
            </dd>
            <dt>关键步骤</dt>
            <dd>
              <ol>
                {guide.key_steps.map((step, index) => (
                  <li key={index}>
                    <MathText text={step} />
                  </li>
                ))}
              </ol>
            </dd>
          </dl>
        </Card>
      )}

      <Card className={styles.folds} aria-label="更多内容">
        {causes.length > 0 && (
          <Fold title="可能原因" hint={`${causes.length} 条`}>
            {causes.map((cause) => (
              <div key={cause.id} className={styles.cause}>
                <strong>
                  <MathText text={cause.label} />
                </strong>
                <span>
                  <MathText text={cause.evidence} />
                </span>
              </div>
            ))}
          </Fold>
        )}
        {diagnosis?.reference_reasoning && (
          <Fold title="参考推导">
            <div className="read">
              <MathText text={diagnosis.reference_reasoning} />
            </div>
          </Fold>
        )}
        {structure && (
          <Fold title="题目结构" hint="已知 · 目标 · 方法">
            <MathText text={structure} />
          </Fold>
        )}
      </Card>

      {detail.topics.length > 0 && (
        <Card className={styles.topicCta}>
          <div>
            <small>本题考点</small>
            <div className={styles.tags}>
              {detail.topics.map((topic) => (
                <Link key={topic.topic_id} to={`/topics/${encodeURIComponent(topic.topic_id)}`}>
                  <Chip>{topic.name}</Chip>
                </Link>
              ))}
            </div>
          </div>
          {practiceCount > 0 && (
            <ButtonLink variant="primary" to={`/practice?topic=${detail.topics[0].topic_id}`}>
              练习这个考点 · {practiceCount} 道 <ArrowRight size={16} aria-hidden />
            </ButtonLink>
          )}
        </Card>
      )}
    </>
  )
}

/** 题目页读取中：左边原卷、右边分析的骨架，避免整页空白。 */
function LoadingLayout() {
  return (
    <div className={styles.layout}>
      <Skeleton variant="question" />
      <Skeleton rows={4} />
    </div>
  )
}

export function QuestionAnalysisPage() {
  const { paperId = '', number = '' } = useParams()
  const questions = usePaperQuestions(paperId)
  const list = questions.data
  const { data: tasks } = useTasks()
  const summary = list?.items.find((question) => question.number === number)
  // 没有分析的题也读取详情，用来显示原卷切图
  const question = useQuestion(summary?.id)
  const detail = question.data
  if (!list)
    return questions.isError ? (
      <ErrorState
        error={questions.error}
        title="题目没能读取"
        onRetry={() => void questions.refetch()}
        back={{ to: `/papers/${paperId}`, label: '回到试卷概览' }}
      />
    ) : (
      <LoadingLayout />
    )
  const analyzing = tasks?.active?.paper_id === paperId
  let analysis
  if (!summary)
    analysis = (
      <Card padded className={styles.notice}>
        这份试卷里没有这道题。
      </Card>
    )
  else if (detail && summary.analysis_available && detail.diagnosis)
    analysis = (
      <>
        <Analysis detail={detail} />
        <ReviewCard paperId={paperId} detail={detail} />
      </>
    )
  else if (question.isError && !detail)
    analysis = (
      <ErrorState
        error={question.error}
        title="这道题没能读取"
        onRetry={() => void question.refetch()}
      />
    )
  else if (question.isPending) analysis = <Skeleton rows={4} />
  else
    analysis = (
      <Card padded className={styles.notice}>
        {summary.analysis_available
          ? '这道题的逐题分析暂时无法显示。'
          : analyzing
            ? '做题龙正在分析这份试卷，完成后会显示在这里。'
            : '这道题还没有逐题分析。'}
      </Card>
    )
  return (
    <>
      <QuestionStrip paperId={paperId} questions={list.items} analyzing={analyzing} />
      <div className={styles.layout}>
        <SourcePanel
          paperId={paperId}
          number={number}
          page={detail?.question.regions[0]?.page ?? null}
          images={detail?.evidence_urls ?? []}
          question={detail?.question}
        />
        <div className={styles.analysis}>
          {analysis}
          <Pager paperId={paperId} questions={list.items} number={number} />
        </div>
      </div>
    </>
  )
}
