import { CircleAlert, CircleCheck, LoaderCircle } from 'lucide-react'
import { Link } from 'react-router'
import { useTasks } from '../../api/queries'
import { SETUP_GUIDE_PATH, setupMessage } from '../../lib/setup'
import styles from './Onboarding.module.css'

/**
 * AI 服务（Codex）的实时可用状态与准备步骤。“Codex”只在这里和使用说明中出现。
 * showGuideLink：是否在步骤下面放“查看配置教程”（设置页自己放在按钮旁边）；
 * onGuide：点教程链接时调用，新手引导用它先关掉对话框。
 */
export function AiServiceStatus({
  showGuideLink = true,
  onGuide,
}: {
  showGuideLink?: boolean
  onGuide?: () => void
}) {
  const { data } = useTasks()
  const availability = data?.availability
  if (!availability || availability.status === 'checking')
    return (
      <div className={styles.status} role="status">
        <LoaderCircle size={22} color="var(--color-primary)" aria-hidden />
        <div>
          <strong>正在检查</strong>
          <small>有分析或批改任务时会自动检查本机的 Codex。</small>
        </div>
      </div>
    )
  if (availability.status === 'available')
    return (
      <div className={styles.status} role="status">
        <CircleCheck size={22} color="var(--status-correct)" aria-hidden />
        <div>
          <strong>已就绪</strong>
          <small>Codex 已安装并登录，上传试卷后会自动开始分析。</small>
        </div>
      </div>
    )
  const notLoggedIn = availability.reason === 'not_logged_in'
  return (
    <>
      <div className={styles.status} role="status">
        <CircleAlert size={22} color="var(--status-partial)" aria-hidden />
        <div>
          <strong>
            {notLoggedIn
              ? '未登录'
              : availability.reason === 'not_installed'
                ? '未安装'
                : availability.reason === 'disabled'
                  ? '未启用'
                  : '暂不可用'}
          </strong>
          <small>
            {notLoggedIn
              ? '本机已安装 Codex，但还没有登录。'
              : availability.reason === 'not_installed'
                ? '这台电脑还没有安装 Codex。'
                : setupMessage(availability)}
          </small>
        </div>
      </div>
      {/* 未启用是做题龙这边关掉了 AI 服务，安装、登录步骤帮不上忙 */}
      {availability.reason !== 'disabled' && (
        <ol className={styles.steps}>
          {!notLoggedIn && <li>按配置教程安装 Codex 命令行工具。</li>}
          <li>用你的 ChatGPT 账号（Plus 等可用套餐）登录 Codex。</li>
          <li>回到做题龙，这里会自动变成“已就绪”，不用重启。</li>
        </ol>
      )}
      {showGuideLink && (
        <Link to={SETUP_GUIDE_PATH} onClick={onGuide}>
          查看配置教程
        </Link>
      )}
    </>
  )
}
