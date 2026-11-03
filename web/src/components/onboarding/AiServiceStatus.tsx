import { CircleAlert, CircleCheck, LoaderCircle } from 'lucide-react'
import { useTasks } from '../../api/queries'
import { setupGuideUrl } from '../../app/config'
import styles from './Onboarding.module.css'

/** AI 服务（Codex）的实时可用状态与准备步骤。“Codex”只在这里和使用说明中出现。 */
export function AiServiceStatus() {
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
                : '暂不可用'}
          </strong>
          <small>
            {notLoggedIn
              ? '本机已安装 Codex，但还没有登录。'
              : availability.reason === 'not_installed'
                ? '这台电脑还没有安装 Codex。'
                : availability.message || 'Codex 暂时不能使用。'}
          </small>
        </div>
      </div>
      <ol className={styles.steps}>
        {!notLoggedIn && <li>按配置教程安装 Codex 命令行工具。</li>}
        <li>用你的 ChatGPT 账号（Plus 等可用套餐）登录 Codex。</li>
        <li>回到做题龙，这里会自动变成“已就绪”，不用重启。</li>
      </ol>
      <a href={setupGuideUrl} target="_blank" rel="noreferrer">
        查看配置教程
      </a>
    </>
  )
}
