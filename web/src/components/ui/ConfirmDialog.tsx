import * as Dialog from '@radix-ui/react-dialog'
import type { ReactNode } from 'react'
import { Button } from './Button'
import styles from './ConfirmDialog.module.css'

/** 需要用户确认后才执行的操作（归档、重新分析、查看会记录曝光的内容等）。 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  children,
  confirmLabel,
  onConfirm,
  pending = false,
  error,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  children: ReactNode
  confirmLabel: string
  onConfirm: () => void
  pending?: boolean
  error?: string | null
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.dialog} aria-describedby={undefined}>
          <Dialog.Title className={styles.title}>{title}</Dialog.Title>
          <div className={styles.body}>{children}</div>
          {error && <p className={styles.error}>{error}</p>}
          <div className={styles.actions}>
            <Dialog.Close asChild>
              <Button disabled={pending}>取消</Button>
            </Dialog.Close>
            <Button variant="primary" disabled={pending} onClick={onConfirm}>
              {pending ? '正在处理…' : confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
