import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleAlert, CircleCheck, LoaderCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { endpoints } from '../../api/endpoints'
import { queryKeys } from '../../api/queries'
import type { TasksResponse } from '../../api/types'
import { desktop, isDesktop } from '../../desktop/bridge'
import { useDesktopRestart } from '../../desktop/useDesktop'
import { friendlyError } from '../../lib/errors'
import { SETUP_GUIDE_PATH, setupMessage } from '../../lib/setup'
import { Button } from '../ui/Button'
import { ButtonRow } from '../ui/ButtonRow'
import styles from './Onboarding.module.css'

type Availability = TasksResponse['availability']

/** 一直“检测中”超过这个时间就给出结果和“重新检查” */
export const CHECK_TIMEOUT_MS = 20_000
/** “检测中”时的刷新间隔（不依赖后台推送） */
const CHECK_POLL_MS = 2_000
/** 自动触发检查的最短间隔：引导和设置页同时挂载时不会重复发起 */
const AUTO_CONNECT_GAP_MS = 30_000
let lastAutoConnect = 0

/** 测试用：清掉自动检查的节流记录 */
export function resetAutoConnectForTests() {
  lastAutoConnect = 0
}

/** “已找到，但不能启动”：程序在，但打不开（例如批处理安装方式）。后端用 reason=other 并给中文说明。 */
export const foundButCannotStart = (a: Availability) =>
  a.status === 'unavailable' && a.reason === 'other' && /已找到/.test(a.message ?? '')

type View = {
  icon: 'checking' | 'ok' | 'warn'
  title: string
  detail: string
  steps: string[]
}

function describe(a: Availability | undefined): View {
  if (!a || a.status === 'checking')
    return {
      icon: 'checking',
      title: '检测中',
      detail: '正在检查这台电脑上的 Codex 是否已安装、已登录。',
      steps: [],
    }
  if (a.status === 'available')
    return {
      icon: 'ok',
      title: '已就绪',
      detail: 'Codex 已安装并登录，上传试卷后会自动开始分析。',
      steps: [],
    }
  if (a.reason === 'not_logged_in')
    return {
      icon: 'warn',
      title: '未登录',
      detail: '这台电脑已经装好 Codex，但还没有登录。',
      steps: [
        '在“开始”菜单打开 PowerShell，输入 codex login，按提示用你的 ChatGPT 账号（Plus 等可用套餐）在浏览器里登录。',
        '回到做题龙，点“重新检查”。',
      ],
    }
  if (a.reason === 'not_installed')
    return {
      icon: 'warn',
      title: '未安装',
      detail: '这台电脑还没有安装 Codex。',
      steps: [
        '按配置教程安装 OpenAI 官方的 Windows 版 Codex（会装好 codex.exe）。不建议用 npm 安装。',
        '用你的 ChatGPT 账号（Plus 等可用套餐）登录一次。',
        '回到做题龙，点“重新检查”。',
      ],
    }
  if (foundButCannotStart(a))
    return {
      icon: 'warn',
      title: '已找到，但不能启动',
      detail: a.message,
      steps: [
        '请安装 OpenAI 官方的 Windows 版 Codex（codex.exe），不要用 npm 安装的版本。',
        '装好后点“重新检查”。',
      ],
    }
  if (a.reason === 'disabled')
    return { icon: 'warn', title: '未启用', detail: setupMessage(a), steps: [] }
  return { icon: 'warn', title: '暂不可用', detail: setupMessage(a), steps: [] }
}

/** 检测超时时的说明（不是失败结论，只是告诉用户可以再查一次） */
const slowCheck: View = {
  icon: 'warn',
  title: '检测时间比较长',
  detail: '还没有查到这台电脑上的 Codex 是否已安装、已登录。可以点“重新检查”，或先跳过，之后再看。',
  steps: [],
}

const icons = {
  checking: <LoaderCircle size={22} color="var(--color-primary)" aria-hidden />,
  ok: <CircleCheck size={22} color="var(--status-correct)" aria-hidden />,
  warn: <CircleAlert size={22} color="var(--status-partial)" aria-hidden />,
}

/**
 * AI 服务（Codex）的实时状态与准备步骤。“Codex”字样只出现在新手引导、AI 未就绪提示和设置说明里。
 * showGuideLink：是否放“查看配置教程”（设置页自己放在按钮旁边）；onGuide：点教程时调用（引导用它先关对话框）。
 */
export function AiServiceStatus({
  showGuideLink = true,
  onGuide,
}: {
  showGuideLink?: boolean
  onGuide?: () => void
}) {
  const client = useQueryClient()
  // 与设置页、侧栏同一个查询；“检测中”时每 2 秒刷新一次，不只等后台推送
  const { data } = useQuery({
    queryKey: queryKeys.tasks,
    queryFn: endpoints.tasks,
    refetchInterval: (query) =>
      query.state.data?.availability.status === 'checking' ? CHECK_POLL_MS : false,
    // 窗口被遮住或在后台时也继续刷新（否则回到窗口前结果一直停在“检测中”）
    refetchIntervalInBackground: true,
  })
  const availability = data?.availability
  const recheck = useMutation({
    mutationFn: endpoints.connectAgent,
    onSettled: () => client.invalidateQueries({ queryKey: queryKeys.tasks }),
  })
  const restart = useDesktopRestart(desktop.restartBackend)
  const checking = !availability || availability.status === 'checking'

  // 后台在“还没检查过”时也报 checking（它只在有任务排队时才自动连接），所以停在这里不会自己变。
  // 看到 checking 就触发一次现有的检查（只探测是否安装、登录，不创建任务）。
  const triggered = useRef(false)
  const status = availability?.status
  useEffect(() => {
    if (status !== 'checking' || triggered.current) return
    triggered.current = true
    if (Date.now() - lastAutoConnect < AUTO_CONNECT_GAP_MS) return
    lastAutoConnect = Date.now()
    recheck.mutate()
    // recheck 每次渲染都是新对象，只按状态触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  // 检测超时：超过 20 秒仍没有结果，给出说明和“重新检查”；点“重新检查”重新计时
  const [timedOut, setTimedOut] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!checking) return
    const timer = window.setTimeout(() => setTimedOut(true), CHECK_TIMEOUT_MS)
    return () => {
      window.clearTimeout(timer)
      setTimedOut(false)
    }
  }, [checking, attempt])

  const view = checking && timedOut ? slowCheck : describe(availability)
  const notReady =
    (availability?.status === 'unavailable' && availability.reason !== 'disabled') ||
    (checking && timedOut) ||
    recheck.isError
  return (
    <>
      <div className={styles.status} role="status" aria-label="AI 服务状态">
        {icons[view.icon]}
        <div>
          <strong>{view.title}</strong>
          <small>{view.detail}</small>
        </div>
      </div>
      {view.steps.length > 0 && (
        <ol className={styles.steps}>
          {view.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      )}
      {notReady && (
        <ButtonRow className={styles.recheck}>
          <Button
            size="sm"
            disabled={recheck.isPending}
            onClick={() => {
              setAttempt((n) => n + 1)
              recheck.mutate()
            }}
          >
            {recheck.isPending ? '正在检查…' : '重新检查'}
          </Button>
          {isDesktop() && (
            <Button
              size="sm"
              variant="ghost"
              disabled={restart.pending || restart.done}
              onClick={() => void restart.run()}
            >
              {restart.done ? '正在重启…' : '重启后台'}
            </Button>
          )}
        </ButtonRow>
      )}
      {notReady && isDesktop() && (
        <p className={styles.hint}>刚装好 Codex 还是检查不到时，点“重启后台”，做题龙会重新查找。</p>
      )}
      {recheck.isError && <p className={styles.error}>{friendlyError(recheck.error)}</p>}
      {restart.error && <p className={styles.error}>{restart.error}</p>}
      {showGuideLink && view.icon !== 'ok' && availability?.reason !== 'disabled' && (
        <Link to={SETUP_GUIDE_PATH} onClick={onGuide}>
          查看配置教程
        </Link>
      )}
    </>
  )
}
