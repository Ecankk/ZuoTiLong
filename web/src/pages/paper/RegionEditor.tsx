import * as Dialog from '@radix-ui/react-dialog'
import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useState, type PointerEvent } from 'react'
import { ApiError } from '../../api/client'
import { endpoints, requestId } from '../../api/endpoints'
import { useAction } from '../../api/queries'
import type { PageImage, Region } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { cx } from '../../lib/cx'
import styles from './RegionEditor.module.css'

export type Segment = { page: number; top: number; bottom: number }

const maxSegments = 4

/** 整页图上离顶部 d 像素（显示高度 H）对应的原卷坐标；整页图原点为 0 */
export const pageY = (image: PageImage, d: number, H: number) =>
  (d * image.image_height) / H / image.scale

/** 原卷坐标在整页图上占的比例（0–1），用于画线和预览 */
const ratio = (image: PageImage, y: number) => (y * image.scale) / image.image_height

/** 现有切图区域换成可编辑的分段；同一页多块合成一段 */
export function segmentsFrom(regions: Region[]): Segment[] {
  const byPage = new Map<number, Segment>()
  for (const region of regions) {
    const [, top, , bottom] = region.bbox
    const seen = byPage.get(region.page)
    if (seen) {
      seen.top = Math.min(seen.top, top)
      seen.bottom = Math.max(seen.bottom, bottom)
    } else byPage.set(region.page, { page: region.page, top, bottom })
  }
  return [...byPage.values()].sort((a, b) => a.page - b.page || a.top - b.top).slice(0, maxSegments)
}

export function regionError(error: Error) {
  if (error instanceof ApiError && error.status === 409)
    return '这份试卷有任务正在进行或已经归档，暂时不能调整切图。等任务结束（或恢复试卷）后再试。'
  if (error instanceof ApiError && error.status === 400)
    return `没能保存：${error.message}。请确认每段的上线在下线上方，并且框住了题目内容。`
  return error.message
}

/** 一段：整页图 + 上下两条可拖动的线 + 切出效果预览 */
function SegmentEditor({
  index,
  segment,
  pages,
  canRemove,
  onChange,
  onRemove,
}: {
  index: number
  segment: Segment
  pages: PageImage[]
  canRemove: boolean
  onChange: (segment: Segment) => void
  onRemove: () => void
}) {
  const image = pages.find((p) => p.page === segment.page) ?? pages[0]
  const [dragging, setDragging] = useState<'top' | 'bottom' | null>(null)
  if (!image) return null
  const pageHeight = image.image_height / image.scale

  const move = (event: PointerEvent<HTMLDivElement>, which: 'top' | 'bottom' | null) => {
    const rect = event.currentTarget.getBoundingClientRect()
    if (!rect.height) return
    const d = Math.min(Math.max(event.clientY - rect.top, 0), rect.height)
    const y = pageY(image, d, rect.height)
    // 没有指定哪条线时，移动离点击位置更近的那条
    const line =
      which ?? (Math.abs(y - segment.top) <= Math.abs(y - segment.bottom) ? 'top' : 'bottom')
    const next = { ...segment, [line]: y }
    if (next.top < next.bottom) onChange(next)
    return line
  }
  const topPct = ratio(image, segment.top) * 100
  const bottomPct = ratio(image, segment.bottom) * 100
  const cropPct = Math.max(bottomPct - topPct, 0.5)

  return (
    <section className={styles.segment} aria-label={`第 ${index + 1} 段`}>
      <div className={styles.segmentHead}>
        <strong>第 {index + 1} 段</strong>
        <label>
          原卷第
          <select
            aria-label={`第 ${index + 1} 段所在页`}
            value={image.page}
            onChange={(event) => {
              const page = Number(event.target.value)
              const target = pages.find((p) => p.page === page) ?? image
              const height = target.image_height / target.scale
              onChange({ page, top: height * 0.1, bottom: height * 0.4 })
            }}
          >
            {pages.map((p) => (
              <option key={p.page} value={p.page}>
                {p.page}
              </option>
            ))}
          </select>
          页
        </label>
        {canRemove && (
          <button type="button" className={styles.remove} onClick={onRemove}>
            <Trash2 size={14} aria-hidden /> 去掉这段
          </button>
        )}
      </div>
      <div className={styles.segmentBody}>
        <div
          className={styles.page}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture?.(event.pointerId)
            setDragging(move(event, null) ?? null)
          }}
          onPointerMove={(event) => dragging && move(event, dragging)}
          onPointerUp={() => setDragging(null)}
        >
          <img
            src={image.image_url}
            alt={`原卷第 ${image.page} 页`}
            draggable={false}
            className={styles.pageImage}
          />
          <span className={styles.shadeTop} style={{ height: `${topPct}%` }} aria-hidden />
          <span className={styles.shadeBottom} style={{ top: `${bottomPct}%` }} aria-hidden />
          <span className={cx(styles.line, styles.topLine)} style={{ top: `${topPct}%` }}>
            <em>上</em>
          </span>
          <span className={cx(styles.line, styles.bottomLine)} style={{ top: `${bottomPct}%` }}>
            <em>下</em>
          </span>
        </div>
        <figure className={styles.preview} aria-label={`第 ${index + 1} 段预览`}>
          <figcaption>切出来的样子</figcaption>
          <div
            className={styles.previewCrop}
            style={{
              aspectRatio: `${image.image_width} / ${(image.image_height * cropPct) / 100}`,
            }}
          >
            <img
              src={image.image_url}
              alt=""
              style={{ top: `${(-topPct / cropPct) * 100}%`, height: `${(100 / cropPct) * 100}%` }}
            />
          </div>
          <small>
            约占整页的 {Math.round(((segment.bottom - segment.top) / pageHeight) * 100)}%
          </small>
        </figure>
      </div>
    </section>
  )
}

function Editor({
  paperId,
  questionId,
  number,
  regions,
  onDone,
}: {
  paperId: string
  questionId: string
  number: string
  regions: Region[]
  onDone: () => void
}) {
  const {
    data: pages,
    isPending,
    error,
  } = useQuery({
    queryKey: ['papers', paperId, 'pages'],
    queryFn: () => endpoints.paperPages(paperId),
  })
  const [segments, setSegments] = useState<Segment[]>(() => segmentsFrom(regions))
  const [confirming, setConfirming] = useState(false)
  // 失败重试沿用同一个 request_id
  const [request] = useState(requestId)
  const save = useAction(
    () => endpoints.adjustRegions(paperId, questionId, request, segments),
    [['questions'], ['papers']],
  )
  const items = pages?.items ?? []
  const add = () => {
    const last = segments[segments.length - 1]
    const next = items.find((p) => p.page > (last?.page ?? 0)) ?? items[0]
    if (!next) return
    const height = next.image_height / next.scale
    setSegments([...segments, { page: next.page, top: height * 0.05, bottom: height * 0.3 }])
  }

  if (confirming)
    return (
      <>
        <p className={styles.text}>只改这道题显示的原卷图，不改判断结果。</p>
        <p className={styles.text}>
          第 {number} 题会按你框出的 {segments.length} 段显示，原来的切图会保留记录。
        </p>
        {save.error && <p className={styles.error}>{regionError(save.error)}</p>}
        <div className={styles.actions}>
          <Button disabled={save.isPending} onClick={() => setConfirming(false)}>
            返回修改
          </Button>
          <Button
            variant="primary"
            disabled={save.isPending}
            onClick={() => save.mutate(undefined, { onSuccess: onDone })}
          >
            {save.isPending ? '正在保存…' : '确认调整'}
          </Button>
        </div>
      </>
    )

  return (
    <>
      <p className={styles.text}>
        拖动红色的上线和蓝色的下线，框出第 {number}{' '}
        题；也可以直接点在图上，离得近的那条线会移过去。题目跨页时加一段。
      </p>
      {isPending && <p className={styles.text}>正在读取原卷…</p>}
      {error && <p className={styles.error}>原卷整页图暂时读不到：{error.message}</p>}
      <div className={styles.segments}>
        {items.length > 0 &&
          segments.map((segment, index) => (
            <SegmentEditor
              key={index}
              index={index}
              segment={segment}
              pages={items}
              canRemove={segments.length > 1}
              onChange={(next) => setSegments(segments.map((s, i) => (i === index ? next : s)))}
              onRemove={() => setSegments(segments.filter((_, i) => i !== index))}
            />
          ))}
      </div>
      <div className={styles.actions}>
        {segments.length < maxSegments && items.length > 0 && (
          <Button variant="ghost" onClick={add}>
            <Plus size={16} aria-hidden /> 加一段（跨页）
          </Button>
        )}
        <Dialog.Close asChild>
          <Button>取消</Button>
        </Dialog.Close>
        <Button variant="primary" disabled={!items.length} onClick={() => setConfirming(true)}>
          下一步
        </Button>
      </div>
    </>
  )
}

/** 题目页原卷图卡片上的“调整切图”：已分析的试卷也能用，只改显示的原卷图。 */
export function AdjustRegionsButton({
  paperId,
  questionId,
  number,
  regions,
}: {
  paperId: string
  questionId: string
  number: string
  regions: Region[]
}) {
  const [open, setOpen] = useState(false)
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" className={styles.trigger}>
          调整切图
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.dialog} aria-describedby={undefined}>
          <Dialog.Title className={styles.title}>调整第 {number} 题的原卷图</Dialog.Title>
          {open && (
            <Editor
              paperId={paperId}
              questionId={questionId}
              number={number}
              regions={regions}
              onDone={() => setOpen(false)}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
