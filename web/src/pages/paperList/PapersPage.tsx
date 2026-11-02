import { FileUp } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import type { PaperScope } from '../../api/endpoints'
import { useImportPaper, usePapers } from '../../api/queries'
import type { Correctness, Paper } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip, type ChipTone } from '../../components/ui/Chip'
import { PageHeader } from '../../components/ui/PageHeader'
import { Segmented } from '../../components/ui/Segmented'
import { cx } from '../../lib/cx'
import { correctnessLabel, monthDay, paperName } from '../../lib/labels'
import styles from './PapersPage.module.css'

/** analysis_status 沿用保存的导入状态，这里只翻译已知值，不当作完成度。 */
const statusText: Record<string, { label: string; tone: ChipTone }> = {
  processing: { label: '正在识别', tone: 'primary' },
  segmented: { label: '已定位题目', tone: 'plain' },
  needs_review: { label: '识别待核对', tone: 'unknown' },
  partial_analysis: { label: '部分已分析', tone: 'plain' },
  diagnosed: { label: '已分析', tone: 'correct' },
}

const today = () => {
  const date = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function UploadCard() {
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [examDate, setExamDate] = useState(today)
  const upload = useImportPaper()
  const navigate = useNavigate()

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!file) return
    upload.mutate(
      { file, title: title.trim() || file.name.replace(/\.pdf$/i, ''), examDate },
      { onSuccess: (result) => navigate(`/papers/${result.paper.id}/questions`) },
    )
  }

  return (
    <Card className={styles.upload} aria-label="上传试卷">
      <div>
        <h2>上传做过的试卷</h2>
        <p>上传整份 PDF，做题龙会先定位每道题，再逐题分析。原文件只保存在这台电脑上。</p>
        <div className={styles.pens}>
          <span>
            <i className={styles.pen} style={{ background: 'var(--text-strong)' }} />
            黑笔：考试作答
          </span>
          <span>
            <i className={styles.pen} style={{ background: 'var(--status-wrong)' }} />
            红笔：事后批改
          </span>
        </div>
      </div>
      <form className={styles.form} onSubmit={submit}>
        <label className={styles.field}>
          试卷名称
          <input
            value={title}
            placeholder="如：2026 数学一"
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          作答日期
          <input
            type="date"
            value={examDate}
            onChange={(event) => setExamDate(event.target.value)}
          />
        </label>
        <label className={styles.fileButton}>
          <FileUp size={16} aria-hidden />
          <span>{file ? file.name : '选择 PDF'}</span>
          <input
            type="file"
            accept="application/pdf"
            aria-label="选择试卷 PDF"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <Button type="submit" variant="primary" disabled={!file || upload.isPending}>
          {upload.isPending ? '正在上传…' : '上传并开始分析'}
        </Button>
      </form>
      {upload.isError && <p className={cx(styles.message, styles.error)}>{upload.error.message}</p>}
    </Card>
  )
}

const countOrder: Correctness[] = ['correct', 'partial', 'wrong', 'unknown']
const countColor: Record<Correctness, string> = {
  correct: 'var(--status-correct)',
  partial: 'var(--status-partial)',
  wrong: 'var(--status-wrong)',
  unknown: 'var(--status-unknown)',
}

function PaperCard({ paper }: { paper: Paper }) {
  const status = statusText[paper.analysis_status]
  const { counts } = paper
  return (
    <Link to={`/papers/${paper.id}/questions`} className={styles.paper}>
      <div className={styles.paperTop}>
        <div>
          <h3>{paperName(paper.title)}</h3>
          <span className={styles.meta}>
            {paper.exam_date ? `${monthDay(paper.exam_date)}作答` : '作答日期未填'}
          </span>
        </div>
        {status && <Chip tone={status.tone}>{status.label}</Chip>}
      </div>
      <span className={styles.score}>
        {paper.score !== null ? (
          <>
            <b>{paper.score}</b> / {paper.total_score} 分
          </>
        ) : (
          '总分待核定'
        )}
      </span>
      {counts.total > 0 ? (
        <>
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
        </>
      ) : (
        <span className={styles.meta}>还没有定位到题目</span>
      )}
    </Link>
  )
}

export function PapersPage() {
  const [scope, setScope] = useState<PaperScope>('0')
  const { data, isError, error } = usePapers(scope)
  return (
    <>
      <PageHeader title="试卷" />
      <UploadCard />
      <div className={styles.listHead}>
        <h2>
          {scope === '0' ? '学习中' : '已归档'}
          {data && <span>{data.total} 份</span>}
        </h2>
        <Segmented<PaperScope>
          label="试卷范围"
          items={[
            { value: '0', label: '学习中' },
            { value: '1', label: '已归档' },
          ]}
          value={scope}
          onChange={setScope}
        />
      </div>
      {isError && (
        <Card padded className={styles.empty}>
          {error.message}
        </Card>
      )}
      {data &&
        (data.items.length === 0 ? (
          <Card padded className={styles.empty}>
            {scope === '0' ? '还没有试卷。上传一份做过的试卷 PDF 开始吧。' : '没有归档的试卷。'}
          </Card>
        ) : (
          <div className={styles.grid}>
            {data.items.map((paper) => (
              <PaperCard key={paper.id} paper={paper} />
            ))}
          </div>
        ))}
    </>
  )
}
