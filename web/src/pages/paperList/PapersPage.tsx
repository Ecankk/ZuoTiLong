import { useQueryClient } from '@tanstack/react-query'
import { CalendarDays, FileUp, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { endpoints, type PaperScope } from '../../api/endpoints'
import { queryKeys, usePapers } from '../../api/queries'
import type { Correctness, ImportResult, Paper } from '../../api/types'
import {
  DuplicateDecisionDialog,
  EditDatesDialog,
  MAX_DATE_BATCH,
} from '../../components/paper/PaperDialogs'
import { ExamDateInput } from '../../components/paper/ExamDateInput'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip, type ChipTone } from '../../components/ui/Chip'
import { ErrorState } from '../../components/ui/ErrorState'
import { PageHeader } from '../../components/ui/PageHeader'
import { Segmented } from '../../components/ui/Segmented'
import { Skeleton } from '../../components/ui/Skeleton'
import { cx } from '../../lib/cx'
import { friendlyError } from '../../lib/errors'
import {
  choiceFrom,
  choiceIncomplete,
  examDateLine,
  NO_DATE,
  sortByExamDate,
  uploadDateFields,
  type DateChoice,
} from '../../lib/examDate'
import { correctnessLabel, paperName } from '../../lib/labels'
import styles from './PapersPage.module.css'

/** analysis_status 沿用保存的导入状态，这里只翻译已知值，不当作完成度。 */
const statusText: Record<string, { label: string; tone: ChipTone }> = {
  processing: { label: '正在识别', tone: 'primary' },
  segmented: { label: '已定位题目', tone: 'plain' },
  needs_review: { label: '识别待核对', tone: 'unknown' },
  partial_analysis: { label: '部分已分析', tone: 'plain' },
  // 正误四色只表示作答结果；“已分析”是完成状态，用中性色
  diagnosed: { label: '已分析', tone: 'plain' },
}

type UploadItem = {
  key: string
  file: File
  title: string
  date: DateChoice
  state: 'waiting' | 'uploading' | 'done' | 'error'
  result?: ImportResult
  error?: string
}

const defaultTitle = (file: File) => file.name.replace(/\.pdf$/i, '')
const isDuplicate = (result?: ImportResult) =>
  result?.duplicate_check?.status === 'same_exam_identity' &&
  result.import_decision === 'pending_duplicate'

function UploadRow({
  item,
  many,
  onChange,
  onRemove,
  onDecide,
}: {
  item: UploadItem
  many: boolean
  onChange: (patch: Partial<UploadItem>) => void
  onRemove: () => void
  onDecide: () => void
}) {
  const locked = item.state !== 'waiting' && item.state !== 'error'
  const { result } = item
  return (
    <li className={styles.uploadRow}>
      <label className={styles.field}>
        {many ? <span className={styles.fileName}>{item.file.name}</span> : '试卷名称'}
        <input
          value={item.title}
          disabled={locked}
          aria-label={`${item.file.name} 的试卷名称`}
          placeholder="如：2026 数学一"
          onChange={(event) => onChange({ title: event.target.value })}
        />
      </label>
      <ExamDateInput
        value={item.date}
        label={many ? `${item.file.name} 的作答日期` : '作答日期'}
        compact={many}
        onChange={(date) => !locked && onChange({ date })}
      />
      <div className={styles.rowState} aria-live="polite">
        {item.state === 'waiting' && !locked && (
          <button
            type="button"
            className={styles.remove}
            aria-label={`不传 ${item.file.name}`}
            onClick={onRemove}
          >
            <X size={16} aria-hidden />
          </button>
        )}
        {item.state === 'uploading' && <span className={styles.muted}>正在上传…</span>}
        {item.state === 'error' && <span className={styles.errorText}>{item.error}</span>}
        {item.state === 'done' && result && (
          <>
            {isDuplicate(result) ? (
              <button type="button" className={styles.linkButton} onClick={onDecide}>
                之前传过同卷，去决定
              </button>
            ) : result.reused ? (
              <Link to={`/papers/${result.paper.id}`}>这个文件之前传过，打开原来那份</Link>
            ) : (
              <Link to={`/papers/${result.paper.id}`}>已上传，去核对题号</Link>
            )}
          </>
        )}
      </div>
    </li>
  )
}

function UploadCard() {
  const [items, setItems] = useState<UploadItem[]>([])
  const [bulk, setBulk] = useState<DateChoice>(NO_DATE)
  const [busy, setBusy] = useState(false)
  const [deciding, setDeciding] = useState<string | null>(null)
  const client = useQueryClient()
  const navigate = useNavigate()
  const many = items.length > 1
  const waiting = items.filter((item) => item.state === 'waiting' || item.state === 'error')
  const incomplete = waiting.some((item) => choiceIncomplete(item.date))
  const decidingItem = items.find((item) => item.key === deciding)

  const patch = (key: string, change: Partial<UploadItem>) =>
    setItems((list) => list.map((item) => (item.key === key ? { ...item, ...change } : item)))

  const pick = (files: FileList | null) => {
    if (!files?.length) return
    const added = Array.from(files).map((file, index) => ({
      key: `${Date.now()}-${index}-${file.name}`,
      file,
      title: defaultTitle(file),
      date: bulk,
      state: 'waiting' as const,
    }))
    // 已经传完的清掉，没传的保留，新选的接在后面
    setItems((list) => [...list.filter((item) => item.state !== 'done'), ...added])
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!waiting.length || incomplete || busy) return
    setBusy(true)
    const results: { key: string; result: ImportResult }[] = []
    for (const item of waiting) {
      patch(item.key, { state: 'uploading', error: undefined })
      try {
        const result = await endpoints.importPaper(
          item.file,
          item.title.trim() || defaultTitle(item.file),
          uploadDateFields(item.date),
        )
        results.push({ key: item.key, result })
        patch(item.key, { state: 'done', result })
      } catch (error) {
        patch(item.key, { state: 'error', error: friendlyError(error) })
      }
    }
    setBusy(false)
    void client.invalidateQueries({ queryKey: ['papers'] })
    void client.invalidateQueries({ queryKey: queryKeys.tasks })
    const duplicate = results.find(({ result }) => isDuplicate(result))
    if (duplicate) setDeciding(duplicate.key)
    else if (items.length === 1 && results.length === 1)
      navigate(`/papers/${results[0].result.paper.id}`)
  }

  const afterDecision = (key: string, decision: 'retake' | 'withdraw') => {
    const item = items.find((entry) => entry.key === key)
    if (!item?.result) return
    if (!many && decision === 'retake') {
      navigate(`/papers/${item.result.paper.id}`)
      return
    }
    if (decision === 'withdraw') setItems((list) => list.filter((entry) => entry.key !== key))
    else
      patch(key, {
        result: { ...item.result, import_decision: 'accepted', duplicate_check: undefined },
      })
    // 还有别的同卷待决定就接着问
    const next = items.find((entry) => entry.key !== key && isDuplicate(entry.result))
    setDeciding(next?.key ?? null)
  }

  return (
    <Card className={styles.upload} aria-label="上传试卷">
      <div className={styles.uploadTop}>
        <div className={styles.intro}>
          <h2>上传做过的试卷</h2>
          <p>
            上传整份
            PDF，可以一次选多份。做题龙会先定位每道题，再逐题分析。原文件只保存在这台电脑上。
          </p>
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
        <label className={styles.fileButton}>
          <FileUp size={16} aria-hidden />
          <span>{items.length ? '再选 PDF' : '选择 PDF'}</span>
          <input
            type="file"
            accept="application/pdf"
            multiple
            aria-label="选择试卷 PDF"
            onChange={(event) => {
              pick(event.target.files)
              event.target.value = ''
            }}
          />
        </label>
      </div>
      {items.length > 0 && (
        <form className={styles.form} onSubmit={(event) => void submit(event)}>
          {many && (
            <div className={styles.bulk}>
              <ExamDateInput label="统一设置作答日期" value={bulk} onChange={setBulk} />
              <Button
                size="sm"
                disabled={busy || choiceIncomplete(bulk)}
                onClick={() =>
                  setItems((list) =>
                    list.map((item) =>
                      item.state === 'waiting' || item.state === 'error'
                        ? { ...item, date: bulk }
                        : item,
                    ),
                  )
                }
              >
                应用到全部
              </Button>
              <span className={styles.muted}>设好后也可以在下面逐份改。</span>
            </div>
          )}
          <ul className={styles.uploadList}>
            {items.map((item) => (
              <UploadRow
                key={item.key}
                item={item}
                many={many}
                onChange={(change) => patch(item.key, change)}
                onRemove={() => setItems((list) => list.filter((entry) => entry.key !== item.key))}
                onDecide={() => setDeciding(item.key)}
              />
            ))}
          </ul>
          <div className={styles.submitRow}>
            {incomplete && (
              <span className={styles.muted}>选了“具体日期”或“约某月”的，请把日子或月份填上。</span>
            )}
            <Button
              type="submit"
              variant="primary"
              disabled={!waiting.length || incomplete || busy}
            >
              {busy ? '正在上传…' : many ? `上传 ${waiting.length} 份` : '上传'}
            </Button>
          </div>
        </form>
      )}
      {decidingItem?.result?.duplicate_check && (
        <DuplicateDecisionDialog
          paperId={decidingItem.result.paper.id}
          check={decidingItem.result.duplicate_check}
          revision={decidingItem.result.decision_revision}
          open
          onOpenChange={(open) => !open && setDeciding(null)}
          onDecided={(decision) => afterDecision(decidingItem.key, decision)}
        />
      )}
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

function PaperCard({
  paper,
  selecting,
  selected,
  onToggle,
}: {
  paper: Paper
  selecting: boolean
  selected: boolean
  onToggle: () => void
}) {
  const pending = paper.import_decision === 'pending_duplicate'
  const status = pending
    ? { label: '待确认是否重做', tone: 'unknown' as const }
    : statusText[paper.analysis_status]
  const { counts } = paper
  return (
    // 整张卡片可点（标题链接铺满卡片），“总分待核定”是卡片上的另一个链接；
    // 选择模式下整张卡片变成勾选框
    <article className={cx(styles.paper, selected && styles.selected)}>
      {selecting && (
        <label className={styles.selectCover}>
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            aria-label={`选择 ${paperName(paper.title)}`}
          />
        </label>
      )}
      <div className={styles.paperTop}>
        <div>
          <h3>
            <Link to={`/papers/${paper.id}/questions`} className={styles.cardLink}>
              {paperName(paper.title)}
            </Link>
          </h3>
          <span className={styles.meta}>{examDateLine(paper)}</span>
        </div>
        {status && <Chip tone={status.tone}>{status.label}</Chip>}
      </div>
      <span className={styles.score}>
        {paper.score !== null ? (
          <>
            <b>{paper.score}</b> / {paper.total_score} 分
          </>
        ) : (
          <>
            <span>总分待核定</span> ·{' '}
            <Link to={`/papers/${paper.id}#score`} className={styles.scoreLink}>
              去核定总分
            </Link>
          </>
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
    </article>
  )
}

export function PapersPage() {
  const [scope, setScope] = useState<PaperScope>('0')
  const { data, error, refetch } = usePapers(scope)
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [editing, setEditing] = useState(false)
  const items = data ? sortByExamDate(data.items) : []
  const toggle = (id: string) =>
    setSelected((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]))
  const stopSelecting = () => {
    setSelecting(false)
    setSelected([])
  }
  const single = selected.length === 1 ? items.find((paper) => paper.id === selected[0]) : undefined
  return (
    <>
      <PageHeader title="试卷" />
      <UploadCard />
      <div className={styles.listHead}>
        <h2>
          {scope === '0' ? '学习中' : '已归档'}
          {data && <span>{data.total} 份</span>}
        </h2>
        <div className={styles.listTools}>
          {data && data.items.length > 0 && !selecting && (
            <Button size="sm" variant="ghost" onClick={() => setSelecting(true)}>
              <CalendarDays size={16} aria-hidden />
              修改作答日期
            </Button>
          )}
          <Segmented<PaperScope>
            label="试卷范围"
            items={[
              { value: '0', label: '学习中' },
              { value: '1', label: '已归档' },
            ]}
            value={scope}
            onChange={(next) => {
              stopSelecting()
              setScope(next)
            }}
          />
        </div>
      </div>
      {selecting && (
        <div className={styles.selectBar} role="region" aria-label="选择要改日期的试卷">
          <span>
            点选要改作答日期的试卷，已选 <b>{selected.length}</b> 份
            {selected.length > MAX_DATE_BATCH && `（一次最多 ${MAX_DATE_BATCH} 份）`}
          </span>
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              setSelected(
                selected.length === items.length
                  ? []
                  : items.slice(0, MAX_DATE_BATCH).map((p) => p.id),
              )
            }
          >
            {selected.length === items.length ? '全不选' : '全选'}
          </Button>
          <Button size="sm" onClick={stopSelecting}>
            取消
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={selected.length === 0 || selected.length > MAX_DATE_BATCH}
            onClick={() => setEditing(true)}
          >
            设置日期
          </Button>
        </div>
      )}
      {!data &&
        (error ? (
          <ErrorState error={error} title="试卷列表没能读取" onRetry={() => void refetch()} />
        ) : (
          <Skeleton variant="rows" rows={2} />
        ))}
      {data &&
        (items.length === 0 ? (
          <Card padded className={styles.empty}>
            {scope === '0' ? '还没有试卷。上传一份做过的试卷 PDF 开始吧。' : '没有归档的试卷。'}
          </Card>
        ) : (
          <div className={styles.grid}>
            {items.map((paper) => (
              <PaperCard
                key={paper.id}
                paper={paper}
                selecting={selecting}
                selected={selected.includes(paper.id)}
                onToggle={() => toggle(paper.id)}
              />
            ))}
          </div>
        ))}
      <EditDatesDialog
        paperIds={selected}
        // 只选一份时回填它现在的日期；多选时先让用户选具体日期，不默认清空
        initial={single ? choiceFrom(single) : { mode: 'day', value: '' }}
        open={editing}
        onOpenChange={setEditing}
        onDone={stopSelecting}
      />
    </>
  )
}
