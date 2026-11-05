import * as Dialog from '@radix-ui/react-dialog'
import { useState, type PointerEvent } from 'react'
import { useQuestion } from '../../api/queries'
import type { EvidenceRegion } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { cx } from '../../lib/cx'
import styles from './CorrectNumbers.module.css'

export type Split = {
  page: number
  y: number
  lower_number: string
  /** 只用于界面回显：切在第几段图、点击时离图顶的距离和图片显示高度 */
  regionIndex: number
  d: number
  H: number
}

/**
 * 图上的点击位置换算成原卷坐标（后端约定）：
 * y = (image_origin[1] + d * image_height / H) / scale，d 为离图片顶部的显示像素，H 为图片显示高度。
 */
export function splitY(region: EvidenceRegion, d: number, H: number) {
  return (region.image_origin[1] + (d * region.image_height) / H) / region.scale
}

/** 下半题号默认取上半题号 + 1 */
export const nextNumber = (number: string) =>
  /^\d+$/.test(number.trim()) ? String(Number(number) + 1) : ''

/** 在这道题的切图上点一下或拖动，定下拆开的位置，再填下半部分的题号。 */
export function SplitDialog({
  questionId,
  number,
  initial,
  onSave,
  onClose,
}: {
  questionId: string
  number: string
  initial?: Split
  onSave: (split: Split) => void
  onClose: () => void
}) {
  const { data, isPending } = useQuestion(questionId)
  const regions = data?.evidence_regions ?? []
  const [mark, setMark] = useState<{ regionIndex: number; d: number; H: number } | null>(
    initial ? { regionIndex: initial.regionIndex, d: initial.d, H: initial.H } : null,
  )
  const [lower, setLower] = useState(initial?.lower_number ?? nextNumber(number))
  const [dragging, setDragging] = useState(false)

  const place = (event: PointerEvent<HTMLImageElement>, regionIndex: number) => {
    const rect = event.currentTarget.getBoundingClientRect()
    if (!rect.height) return
    const d = Math.min(Math.max(event.clientY - rect.top, 0), rect.height)
    setMark({ regionIndex, d, H: rect.height })
  }
  const save = () => {
    const region = regions.find((r) => r.region_index === mark?.regionIndex)
    if (!region || !mark) return
    onSave({
      page: region.page,
      y: splitY(region, mark.d, mark.H),
      lower_number: lower.trim(),
      ...mark,
    })
  }

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={cx(styles.dialog, styles.splitDialog)}
          aria-describedby={undefined}
        >
          <Dialog.Title className={styles.title}>把第 {number} 题拆成两题</Dialog.Title>
          <p className={styles.text}>
            在图上点一下两道题之间的空白处，或按住拖动来调整位置。线以上仍是第 {number}{' '}
            题，线以下成为新的一题。
          </p>
          <div className={styles.splitImages}>
            {isPending && <p className={styles.text}>正在读取切图…</p>}
            {!isPending && regions.length === 0 && (
              <p className={styles.error}>这道题的切图暂时读不到，不能拆分。</p>
            )}
            {regions.map((region) => (
              <div key={region.region_index} className={styles.splitFrame}>
                <img
                  src={region.image_url}
                  alt={`第 ${number} 题切图${regions.length > 1 ? `（第 ${region.region_index + 1} 段）` : ''}`}
                  draggable={false}
                  className={styles.splitImage}
                  onPointerDown={(event) => {
                    setDragging(true)
                    event.currentTarget.setPointerCapture?.(event.pointerId)
                    place(event, region.region_index)
                  }}
                  onPointerMove={(event) => dragging && place(event, region.region_index)}
                  onPointerUp={() => setDragging(false)}
                />
                {mark?.regionIndex === region.region_index && (
                  <span
                    className={styles.splitLine}
                    style={{ top: `${(mark.d / mark.H) * 100}%` }}
                    aria-hidden
                  />
                )}
              </div>
            ))}
          </div>
          <div className={styles.splitForm}>
            <label className={styles.numberField}>
              下半部分的题号
              <input value={lower} onChange={(event) => setLower(event.target.value)} />
            </label>
            {!mark && regions.length > 0 && <span className={styles.hint}>先在图上选好位置</span>}
          </div>
          <div className={styles.actions}>
            <Button onClick={onClose}>取消</Button>
            <Button variant="primary" disabled={!mark || !lower.trim()} onClick={save}>
              在这里拆开
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
