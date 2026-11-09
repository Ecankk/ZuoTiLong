import { Eye } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { endpoints } from '../../api/endpoints'
import { useAction } from '../../api/queries'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { friendlyError } from '../../lib/errors'

/**
 * 查看被遮挡的题目或解析：先确认，确认后会记录曝光。
 * 遮挡卡上“查看题目”是这张卡唯一的操作，用 primary；次要位置用 ghost。
 */
export function RevealButton({
  bankId,
  kind,
  label,
  children,
  variant = 'soft',
  onRevealed,
}: {
  bankId: string
  kind: 'question' | 'analysis'
  label: string
  children: ReactNode
  variant?: 'primary' | 'soft' | 'ghost'
  /** 确认查看成功后（如自由练习页重新读取题目） */
  onRevealed?: () => void
}) {
  const [open, setOpen] = useState(false)
  const reveal = useAction(() => endpoints.reveal(bankId, kind), [['practices'], ['bank']])
  return (
    <>
      <Button
        variant={variant}
        size={variant === 'ghost' ? 'sm' : 'md'}
        onClick={() => setOpen(true)}
      >
        <Eye size={16} aria-hidden />
        {label}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={kind === 'question' ? '查看这道题？' : '查看参考解析？'}
        confirmLabel={kind === 'question' ? '确认查看题目' : '确认查看解析'}
        pending={reveal.isPending}
        error={reveal.error ? friendlyError(reveal.error) : undefined}
        onConfirm={() =>
          reveal.mutate(undefined, {
            onSuccess: () => {
              setOpen(false)
              onRevealed?.()
            },
          })
        }
      >
        {children}
      </ConfirmDialog>
    </>
  )
}
