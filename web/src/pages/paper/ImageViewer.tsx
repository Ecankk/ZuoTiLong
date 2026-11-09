import * as Dialog from '@radix-ui/react-dialog'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Maximize, Minus, Plus, X } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from 'react'
import { endpoints } from '../../api/endpoints'
import type { Region } from '../../api/types'
import { cx } from '../../lib/cx'
import { friendlyError } from '../../lib/errors'
import styles from './ImageViewer.module.css'

/** 看图层打开的内容：本题切图的第几段，或原卷第几页（整页并框出本题区域） */
export type ViewerTarget = { mode: 'crop'; index: number } | { mode: 'page'; page: number }

/** 高亮框，取值为占整张图的比例（0–1） */
type Box = { left: number; top: number; width: number; height: number }

type Zoom = { scale: number; x: number; y: number }

const MIN_SCALE = 1
const MAX_SCALE = 8
const STEP = 1.4
const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

/**
 * 可缩放、拖动的单张图：滚轮缩放（以指针为中心），按住拖动，双击放大 / 还原。
 * scale=1 时整张图适应窗口。
 */
function ZoomView({
  src,
  alt,
  boxes = [],
  onFail,
}: {
  src: string
  alt: string
  boxes?: Box[]
  onFail: () => void
}) {
  const stageRef = useRef<HTMLDivElement>(null)
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null)
  const [stage, setStage] = useState({ w: 0, h: 0 })
  const [zoom, setZoom] = useState<Zoom>({ scale: 1, x: 0, y: 0 })
  const drag = useRef<{ id: number; x: number; y: number; zoom: Zoom } | null>(null)

  useLayoutEffect(() => {
    const element = stageRef.current
    if (!element) return
    const measure = () => setStage({ w: element.clientWidth, h: element.clientHeight })
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // 适应窗口的尺寸；小图最多放大到 2 倍，避免糊成一片
  const fit = natural ? Math.min((stage.w - 32) / natural.w, (stage.h - 32) / natural.h, 2) : 0
  const baseW = natural ? natural.w * fit : 0
  const baseH = natural ? natural.h * fit : 0

  /** 平移不超过图片边缘：放大后最多拖到图边贴住窗口边 */
  const bound = useCallback(
    (next: Zoom): Zoom => {
      const maxX = Math.max(0, (baseW * next.scale - stage.w) / 2 + 16)
      const maxY = Math.max(0, (baseH * next.scale - stage.h) / 2 + 16)
      return { scale: next.scale, x: clamp(next.x, -maxX, maxX), y: clamp(next.y, -maxY, maxY) }
    },
    [baseW, baseH, stage.w, stage.h],
  )

  /** 以窗口内一点（相对舞台左上角）为中心缩放 */
  const zoomAt = useCallback(
    (factor: number, point?: { x: number; y: number }) =>
      setZoom((prev) => {
        const scale = clamp(prev.scale * factor, MIN_SCALE, MAX_SCALE)
        if (scale === MIN_SCALE) return { scale, x: 0, y: 0 }
        const mx = (point?.x ?? stage.w / 2) - stage.w / 2
        const my = (point?.y ?? stage.h / 2) - stage.h / 2
        const ratio = scale / prev.scale
        return bound({ scale, x: mx - ratio * (mx - prev.x), y: my - ratio * (my - prev.y) })
      }),
    [bound, stage.w, stage.h],
  )

  // React 的 wheel 监听是被动的，这里用原生监听才能阻止页面滚动
  useEffect(() => {
    const element = stageRef.current
    if (!element) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const rect = element.getBoundingClientRect()
      zoomAt(Math.exp(-event.deltaY * 0.0015), {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      })
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => element.removeEventListener('wheel', onWheel)
  }, [zoomAt])

  const point = (event: { clientX: number; clientY: number }) => {
    const rect = stageRef.current?.getBoundingClientRect()
    return rect ? { x: event.clientX - rect.left, y: event.clientY - rect.top } : undefined
  }

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || zoom.scale === 1) return
    event.currentTarget.setPointerCapture?.(event.pointerId)
    drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, zoom }
  }
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const start = drag.current
    if (!start || start.id !== event.pointerId) return
    setZoom(
      bound({
        scale: start.zoom.scale,
        x: start.zoom.x + event.clientX - start.x,
        y: start.zoom.y + event.clientY - start.y,
      }),
    )
  }
  const endDrag = () => {
    drag.current = null
  }

  // + − 0 键缩放：看图层是模态的，同一时间只有一个 ZoomView
  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey) return
      if (event.key === '+' || event.key === '=') zoomAt(STEP)
      else if (event.key === '-') zoomAt(1 / STEP)
      else if (event.key === '0') setZoom({ scale: 1, x: 0, y: 0 })
      else return
      event.preventDefault()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [zoomAt])

  return (
    <>
      <div
        ref={stageRef}
        className={cx(styles.stage, zoom.scale > 1 && styles.zoomed)}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onDoubleClick={(event) =>
          zoom.scale > 1 ? setZoom({ scale: 1, x: 0, y: 0 }) : zoomAt(2.5, point(event))
        }
      >
        <div
          className={styles.frame}
          style={
            natural
              ? {
                  width: baseW,
                  height: baseH,
                  transform: `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.scale})`,
                }
              : { visibility: 'hidden' }
          }
        >
          <img
            src={src}
            alt={alt}
            draggable={false}
            onLoad={(event) =>
              setNatural({
                w: event.currentTarget.naturalWidth || 1,
                h: event.currentTarget.naturalHeight || 1,
              })
            }
            onError={onFail}
          />
          {boxes.map((box, index) => (
            <span
              key={index}
              className={styles.box}
              style={{
                left: `${box.left * 100}%`,
                top: `${box.top * 100}%`,
                width: `${box.width * 100}%`,
                height: `${box.height * 100}%`,
              }}
              aria-hidden
            />
          ))}
        </div>
        {!natural && <p className={styles.message}>正在读取图片…</p>}
      </div>
      <div className={styles.zoomBar} aria-label="缩放">
        <button type="button" onClick={() => zoomAt(1 / STEP)} title="缩小（−）">
          <Minus size={16} aria-hidden />
        </button>
        <span className={styles.percent} aria-live="polite">
          {zoom.scale === 1 ? '适应窗口' : `${Math.round(zoom.scale * 100)}%`}
        </span>
        <button type="button" onClick={() => zoomAt(STEP)} title="放大（+）">
          <Plus size={16} aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => setZoom({ scale: 1, x: 0, y: 0 })}
          disabled={zoom.scale === 1}
          title="适应窗口（0）"
        >
          <Maximize size={15} aria-hidden />
        </button>
      </div>
    </>
  )
}

/** 整页模式：读取整页图列表，显示目标页并框出本题在这一页上的区域 */
function PageView({
  paperId,
  page,
  regions,
  number,
  onPage,
}: {
  paperId: string
  page: number
  regions: Region[]
  number: string
  onPage: (page: number) => void
}) {
  const { data, error } = useQuery({
    queryKey: ['papers', paperId, 'pages'],
    queryFn: () => endpoints.paperPages(paperId),
  })
  const [failed, setFailed] = useState<string | null>(null)
  if (error) return <p className={styles.message}>原卷整页图暂时读不到：{friendlyError(error)}</p>
  if (!data) return <p className={styles.message}>正在读取原卷…</p>
  const items = data.items
  const index = Math.max(
    items.findIndex((item) => item.page === page),
    0,
  )
  const image = items[index]
  if (!image) return <p className={styles.message}>这份试卷没有可显示的整页图。</p>
  const boxes: Box[] = regions
    .filter((region) => region.page === image.page)
    .map(({ bbox: [x0, y0, x1, y1] }) => ({
      left: (x0 * image.scale) / image.image_width,
      top: (y0 * image.scale) / image.image_height,
      width: ((x1 - x0) * image.scale) / image.image_width,
      height: ((y1 - y0) * image.scale) / image.image_height,
    }))
  const previous = items[index - 1]
  const next = items[index + 1]
  return (
    <>
      <Pager
        label={`第 ${image.page} / ${items.length} 页`}
        note={boxes.length ? `框出的是第 ${number} 题` : `第 ${number} 题不在这一页`}
        onPrevious={previous && (() => onPage(previous.page))}
        onNext={next && (() => onPage(next.page))}
        previousLabel="上一页"
        nextLabel="下一页"
      />
      {failed === image.image_url ? (
        <p className={styles.message}>这一页的图暂时无法显示。</p>
      ) : (
        <ZoomView
          key={image.image_url}
          src={image.image_url}
          alt={`原卷第 ${image.page} 页`}
          boxes={boxes}
          onFail={() => setFailed(image.image_url)}
        />
      )}
    </>
  )
}

function Pager({
  label,
  note,
  onPrevious,
  onNext,
  previousLabel,
  nextLabel,
}: {
  label: string
  note?: string
  onPrevious?: () => void
  onNext?: () => void
  previousLabel: string
  nextLabel: string
}) {
  return (
    <div className={styles.pager}>
      <button type="button" onClick={onPrevious} disabled={!onPrevious} title={previousLabel}>
        <ChevronLeft size={16} aria-hidden />
        {previousLabel}
      </button>
      <span>
        {label}
        {note && <small>{note}</small>}
      </span>
      <button type="button" onClick={onNext} disabled={!onNext} title={nextLabel}>
        {nextLabel}
        <ChevronRight size={16} aria-hidden />
      </button>
    </div>
  )
}

/**
 * 应用内看图层：本题切图 / 整页两种模式，可缩放、拖动。
 * 不再打开新标签页（打包成桌面应用后新标签页会跳出应用）。
 */
export function ImageViewer({
  target,
  onTargetChange,
  paperId,
  number,
  crops,
  regions,
}: {
  target: ViewerTarget | null
  onTargetChange: (target: ViewerTarget | null) => void
  paperId: string
  number: string
  crops: string[]
  regions: Region[]
}) {
  const [failedCrop, setFailedCrop] = useState<string | null>(null)
  // 与调整切图共用同一份整页图列表
  const pages = useQuery({
    queryKey: ['papers', paperId, 'pages'],
    queryFn: () => endpoints.paperPages(paperId),
    enabled: target?.mode === 'page',
  })
  const pageCount = pages.data?.items.length ?? 0
  const firstPage = regions[0]?.page ?? 1
  const cropIndex = target?.mode === 'crop' ? clamp(target.index, 0, crops.length - 1) : 0
  const crop = crops[cropIndex]

  // ← / → 切换切图分段或整页页码；缩放键由 ZoomView 处理
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!target || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return
    event.stopPropagation()
    const delta = event.key === 'ArrowLeft' ? -1 : 1
    if (target.mode === 'crop') {
      const index = target.index + delta
      if (index >= 0 && index < crops.length) onTargetChange({ mode: 'crop', index })
    } else {
      const page = target.page + delta
      if (page >= 1 && page <= pageCount) onTargetChange({ mode: 'page', page })
    }
  }

  return (
    <Dialog.Root open={target !== null} onOpenChange={(open) => !open && onTargetChange(null)}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={styles.viewer}
          aria-describedby={undefined}
          onKeyDown={onKeyDown}
        >
          <div className={styles.head}>
            <Dialog.Title className={styles.title}>第 {number} 题原卷</Dialog.Title>
            <div className={styles.modes} role="group" aria-label="查看方式">
              <button
                type="button"
                aria-pressed={target?.mode === 'crop'}
                disabled={crops.length === 0}
                onClick={() => onTargetChange({ mode: 'crop', index: 0 })}
              >
                本题切图
              </button>
              <button
                type="button"
                aria-pressed={target?.mode === 'page'}
                onClick={() => onTargetChange({ mode: 'page', page: firstPage })}
              >
                整页
              </button>
            </div>
            <Dialog.Close className={styles.close} title="关闭（Esc）">
              <X size={18} aria-hidden />
              <span>关闭</span>
            </Dialog.Close>
          </div>
          <div className={styles.body}>
            {target?.mode === 'page' ? (
              <PageView
                paperId={paperId}
                page={target.page}
                regions={regions}
                number={number}
                onPage={(page) => onTargetChange({ mode: 'page', page })}
              />
            ) : crop ? (
              <>
                {crops.length > 1 && (
                  <Pager
                    label={`第 ${cropIndex + 1} / ${crops.length} 段`}
                    onPrevious={
                      cropIndex > 0
                        ? () => onTargetChange({ mode: 'crop', index: cropIndex - 1 })
                        : undefined
                    }
                    onNext={
                      cropIndex < crops.length - 1
                        ? () => onTargetChange({ mode: 'crop', index: cropIndex + 1 })
                        : undefined
                    }
                    previousLabel="上一段"
                    nextLabel="下一段"
                  />
                )}
                {failedCrop === crop ? (
                  <p className={styles.message}>原卷切图暂时无法显示，可以切换到“整页”查看。</p>
                ) : (
                  <ZoomView
                    key={crop}
                    src={crop}
                    alt={`第 ${number} 题原卷切图 ${cropIndex + 1}`}
                    onFail={() => setFailedCrop(crop)}
                  />
                )}
              </>
            ) : (
              <p className={styles.message}>这道题没有切图，可以切换到“整页”查看。</p>
            )}
          </div>
          <p className={styles.hint}>滚轮缩放 · 放大后按住拖动 · 双击放大或还原 · Esc 关闭</p>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
