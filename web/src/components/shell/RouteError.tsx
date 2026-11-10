import { RotateCw } from 'lucide-react'
import { isRouteErrorResponse, useRouteError } from 'react-router'
import { Button, ButtonLink } from '../ui/Button'
import { ButtonRow } from '../ui/ButtonRow'
import { Card } from '../ui/Card'
import styles from './RouteError.module.css'

/** 按需加载的页面文件下载失败（断网或做题龙关了）时浏览器给出的错误 */
export function isChunkLoadError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error ?? '')
  return /dynamically imported module|Importing a module script failed|Failed to fetch|Loading chunk|error loading/i.test(
    message,
  )
}

/**
 * 路由级错误边界：替代 React Router 的英文 “Unexpected Application Error”。
 * 外壳（侧栏）保留，内容区显示中文说明和“重新加载”。
 */
export function RouteError() {
  const error = useRouteError()
  const notFound = isRouteErrorResponse(error) && error.status === 404
  const offline = isChunkLoadError(error)
  return (
    <Card padded className={styles.card} role="alert">
      <strong>{notFound ? '没有找到这个页面' : offline ? '页面没能打开' : '页面出了点问题'}</strong>
      <p>
        {notFound
          ? '这个地址没有对应的页面，可能链接已经过期。'
          : offline
            ? '连不上做题龙，这个页面没能加载。请确认做题龙还开着，再点“重新加载”。'
            : '这个页面暂时显示不了。可以重新加载试试；已保存的内容不会受影响。'}
      </p>
      <ButtonRow className={styles.actions}>
        <Button variant="primary" onClick={() => window.location.reload()}>
          <RotateCw size={16} aria-hidden /> 重新加载
        </Button>
        <ButtonLink variant="ghost" to="/">
          回到首页
        </ButtonLink>
      </ButtonRow>
    </Card>
  )
}
