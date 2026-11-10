import { CircleAlert, RotateCw, WifiOff } from 'lucide-react'
import { friendlyError, isOffline } from '../../lib/errors'
import { Button, ButtonLink } from './Button'
import { ButtonRow } from './ButtonRow'
import { Card } from './Card'
import styles from './ErrorState.module.css'

/**
 * 读取失败时的统一提示：一句中文说明 + “重试” + 可选的返回路径。
 * - `error`：任何错误对象（会经过 friendlyError，不显示英文原始报错）
 * - `onRetry`：通常传 react-query 的 `refetch`
 * - `back`：例如 `{ to: '/papers', label: '回到试卷列表' }`
 * - `inline`：放在卡片内部时用，不再包一层卡片
 */
export function ErrorState({
  error,
  title,
  onRetry,
  back,
  inline = false,
}: {
  error: unknown
  title?: string
  onRetry?: () => void
  back?: { to: string; label: string }
  inline?: boolean
}) {
  const offline = isOffline(error)
  const Icon = offline ? WifiOff : CircleAlert
  const body = (
    <div className={styles.state} role="alert">
      <Icon size={22} className={styles.icon} aria-hidden />
      <div className={styles.text}>
        <strong>{title ?? (offline ? '连接中断' : '没能读取')}</strong>
        <p>{friendlyError(error)}</p>
        {(onRetry || back) && (
          <ButtonRow className={styles.actions}>
            {onRetry && (
              <Button size="sm" onClick={onRetry}>
                <RotateCw size={14} aria-hidden /> 重试
              </Button>
            )}
            {back && (
              <ButtonLink size="sm" variant="ghost" to={back.to}>
                {back.label}
              </ButtonLink>
            )}
          </ButtonRow>
        )}
      </div>
    </div>
  )
  return inline ? body : <Card padded>{body}</Card>
}
