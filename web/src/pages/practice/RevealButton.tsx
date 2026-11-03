import { Eye } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { endpoints } from '../../api/endpoints'
import { useAction } from '../../api/queries'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'

/** 查看被遮挡的题目或解析：先确认，确认后会记录曝光。 */
export function RevealButton({
  bankId,
  kind,
  label,
  children,
  variant = 'soft',
}: {
  bankId: string
  kind: 'question' | 'analysis'
  label: string
  children: ReactNode
  variant?: 'soft' | 'ghost'
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
        error={reveal.error?.message}
        onConfirm={() => reveal.mutate(undefined, { onSuccess: () => setOpen(false) })}
      >
        {children}
      </ConfirmDialog>
    </>
  )
}
