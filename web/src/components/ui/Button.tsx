import type { ButtonHTMLAttributes } from 'react'
import { Link, type LinkProps } from 'react-router'
import { cx } from '../../lib/cx'
import styles from './Button.module.css'

type Variant = 'primary' | 'secondary' | 'ghost' | 'soft'
type Size = 'sm' | 'md' | 'lg'
type Look = { variant?: Variant; size?: Size }

const lookClass = ({ variant = 'secondary', size = 'md' }: Look, className?: string) =>
  cx(
    styles.button,
    variant !== 'secondary' && styles[variant],
    size !== 'md' && styles[size],
    className,
  )

export function Button({
  variant,
  size,
  className,
  type = 'button',
  ...props
}: Look & ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type={type} className={lookClass({ variant, size }, className)} {...props} />
}

/** 外观同按钮的页面跳转。 */
export function ButtonLink({ variant, size, className, ...props }: Look & LinkProps) {
  return <Link className={lookClass({ variant, size }, className)} {...props} />
}
