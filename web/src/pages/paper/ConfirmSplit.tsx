import * as Dialog from '@radix-ui/react-dialog'
import { ArrowRight, X } from 'lucide-react'
import { useState } from 'react'
import { endpoints } from '../../api/endpoints'
import { useAction, usePaperQuestions, useQuestion, useTasks } from '../../api/queries'
import type { PaperResponse, QuestionSummary, Task } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip } from '../../components/ui/Chip'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { friendlyError } from '../../lib/errors'
import { CorrectNumbersButton } from './CorrectNumbers'
import styles from './ConfirmSplit.module.css'
import { LoadingImage } from '../../components/ui/LoadingImage'

/**
 * 已切题、还没开始分析：可以分析、还没有分析结果、也没有该卷的排队或运行任务。
 * 后端会提供专门的状态字段（B11），届时在这里对齐。
 */
export function awaitingSplitConfirm(data: PaperResponse, tasks: Task[] | undefined) {
  const busy = tasks?.some(
    (task) =>
      task.paper_id === data.paper.id && (task.status === 'queued' || task.status === 'running'),
  )
  return (
    !data.paper.archived_at &&
    data.analysis.report_id === null &&
    data.actions.includes('analyze') &&
    data.paper.import_decision !== 'pending_duplicate' &&
    data.paper.counts.total > 0 &&
    !busy
  )
}

const byNumber = (a: QuestionSummary, b: QuestionSummary) => Number(a.number) - Number(b.number)

/** 点开一道题看原卷切图（可能有多块区域） */
function CropDialog({ question, onClose }: { question: QuestionSummary; onClose: () => void }) {
  const { data } = useQuestion(question.id)
  const urls = data?.evidence_urls.length
    ? data.evidence_urls
    : [`/api/questions/${encodeURIComponent(question.id)}/evidence?region=0`]
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.dialog} aria-describedby={undefined}>
          <header className={styles.dialogHead}>
            <Dialog.Title>第 {question.number} 题的原卷切图</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className={styles.close} aria-label="关闭">
                <X size={18} aria-hidden />
              </button>
            </Dialog.Close>
          </header>
          {urls.map((url, index) => (
            <LoadingImage
              key={url}
              className={styles.crop}
              src={url}
              alt={`第 ${question.number} 题切图 ${index + 1}`}
            />
          ))}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

/** 上传后的第一步：核对做题龙切出的题号，没问题再开始分析。 */
export function ConfirmSplitCard({ data }: { data: PaperResponse }) {
  const { paper } = data
  const { data: list } = usePaperQuestions(paper.id)
  const { data: tasks } = useTasks()
  const [confirm, setConfirm] = useState(false)
  const [viewing, setViewing] = useState<QuestionSummary | null>(null)
  // 这个弹窗本身就是确认步骤；后端首次分析也要求 confirmed:true
  const analyze = useAction(
    () => endpoints.analyzePaper(paper.id, true),
    [['papers'], ['questions'], ['tasks']],
  )
  const questions = [...(list?.items ?? [])].sort(byNumber)
  const unavailable = tasks?.availability.status === 'unavailable'

  return (
    <Card padded className={styles.card} aria-label="核对切题">
      <Chip tone="primary">第一步 · 核对切题</Chip>
      <h2>做题龙找到了 {paper.counts.total} 道题，先核对一下题号</h2>
      <p className={styles.text}>
        点题号可以看对应的原卷切图。如果有题被切开、多出不是题目的部分，或题号不对，先纠正题号；没问题就开始分析。
      </p>
      <ol className={styles.numbers} aria-label="题号">
        {questions.map((question) => (
          <li key={question.id}>
            <button
              type="button"
              className={styles.number}
              title={`查看第 ${question.number} 题的原卷切图`}
              onClick={() => setViewing(question)}
            >
              {question.number}
            </button>
          </li>
        ))}
      </ol>
      <div className={styles.actions}>
        <Button variant="primary" size="lg" onClick={() => setConfirm(true)}>
          题号没问题，开始分析 <ArrowRight size={16} aria-hidden />
        </Button>
        <CorrectNumbersButton paperId={paper.id} />
      </div>
      {viewing && <CropDialog question={viewing} onClose={() => setViewing(null)} />}
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="开始分析这份试卷？"
        confirmLabel="开始分析"
        pending={analyze.isPending}
        error={analyze.error ? friendlyError(analyze.error) : null}
        onConfirm={() => analyze.mutate(undefined, { onSuccess: () => setConfirm(false) })}
      >
        <p>
          做题龙会用本机的 AI
          服务逐题分析，整份试卷通常需要较长时间。期间可以离开这个页面，进度会显示在左下角。
        </p>
        <p className={styles.note}>
          {unavailable
            ? 'AI 服务现在还没准备好，分析会先排队，准备好后自动开始。'
            : '开始分析后就不能再纠正题号了。'}
        </p>
      </ConfirmDialog>
    </Card>
  )
}
