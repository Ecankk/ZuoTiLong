import { Check, X } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Correctness } from '../../api/types'
import { cx } from '../../lib/cx'
import { correctnessLabel } from '../../lib/labels'
import styles from './Chip.module.css'

export type ChipTone = Correctness | 'primary' | 'plain'

export function Chip({
  tone = 'plain',
  className,
  children,
}: {
  tone?: ChipTone
  className?: string
  children: ReactNode
}) {
  return <span className={cx(styles.chip, styles[tone], className)}>{children}</span>
}

export function CorrectnessChip({ value, className }: { value: Correctness; className?: string }) {
  return (
    <Chip tone={value} className={className}>
      {value === 'wrong' && <X aria-hidden />}
      {value === 'correct' && <Check aria-hidden />}
      {correctnessLabel[value]}
    </Chip>
  )
}
