import { useTasks } from '../../api/queries'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { isDesktop } from '../../desktop/bridge'
import { setupMessage } from '../../lib/setup'
import styles from './SetupHelpPage.module.css'

/** 应用内的配置教程：让做题龙能分析试卷、批改作答（准备 Codex）。不依赖外网页面。 */
export function SetupHelpPage() {
  const { data } = useTasks()
  const availability = data?.availability
  const ready = availability?.status === 'available'
  return (
    <>
      <PageHeader title="配置教程" subtitle="一次性设置，完成后分析和批改会自动开始。" />
      <div className={styles.stack}>
        <Card padded className={styles.status} aria-label="现在的状态">
          <strong>{ready ? '已经准备好了' : '还没有准备好'}</strong>
          <p>
            {ready
              ? '做题龙可以分析试卷、批改作答了，不需要再做什么。'
              : availability
                ? setupMessage(availability)
                : '正在检查…'}
          </p>
        </Card>
        <Card padded aria-label="准备步骤">
          <h2>准备步骤</h2>
          <ol className={styles.steps}>
            <li>
              <strong>安装官方的 Windows 版 Codex</strong>
              <p>
                做题龙借助本机的 Codex 分析试卷、批改作答。请按 OpenAI 官方说明安装 Windows 版
                Codex，它会在电脑上装好 <code>codex.exe</code>。不建议用 npm
                安装：那种安装方式做题龙不能可靠地启动。装好后，在“开始”菜单打开 PowerShell，输入
                <code>codex --version</code>，能看到版本号就说明装好了。
              </p>
            </li>
            <li>
              <strong>登录一次</strong>
              <p>
                在 PowerShell 里输入 <code>codex login</code>，按提示在浏览器里用你的 ChatGPT
                账号（Plus 等可用套餐）登录。输入 <code>codex login status</code> 可以确认已登录。
              </p>
            </li>
            <li>
              <strong>回到做题龙</strong>
              <p>不用重启。做题龙会自动检测，侧栏左下角变成正常状态后就可以开始分析了。</p>
            </li>
          </ol>
        </Card>
        <Card padded aria-label="常见问题">
          <h2>常见问题</h2>
          <dl className={styles.faq}>
            <dt>已经装了 Codex，还是提示没有安装？</dt>
            <dd>
              {isDesktop()
                ? '在新手引导或“设置 → 使用说明”里点“重启后台”，做题龙会重新查找新装的程序；也可以在“设置 → AI 服务位置”里直接选择 codex.exe。'
                : '装好后需要重新打开做题龙的启动器，让它找到新装的程序。'}
            </dd>
            <dt>提示“已找到，但不能启动”？</dt>
            <dd>
              多半是用 npm 装的版本。请改装官方的 Windows 版 Codex（codex.exe），再点“重新检查”。
            </dd>
            <dt>没准备好时还能用吗？</dt>
            <dd>
              可以。已上传的试卷、已有的分析和练习都能查看；只是新的分析和批改要等准备好后才会进行。
            </dd>
            <dt>需要填写网址或密钥吗？</dt>
            <dd>不需要。做题龙沿用本机 Codex 的登录。</dd>
          </dl>
        </Card>
      </div>
    </>
  )
}
