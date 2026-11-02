import * as Popover from '@radix-ui/react-popover'
import { ChevronRight } from 'lucide-react'
import { useTasks } from '../../api/queries'
import type { Task, TasksResponse } from '../../api/types'
import { setupGuideUrl } from '../../app/config'
import { Button } from '../ui/Button'
import styles from './BackgroundIndicator.module.css'

const setupMessages: Record<string, string> = {
  not_installed:
    '这台电脑还没有安装做题龙需要的 Codex。按教程完成一次性设置后，分析和批改会自动开始。',
  not_logged_in: '做题龙需要的 Codex 还没有登录。按教程登录一次后，分析和批改会自动开始。',
}

function SetupGuide({ availability }: { availability: TasksResponse['availability'] }) {
  const message =
    setupMessages[availability.reason ?? ''] ??
    (availability.message || '做题龙暂时不能工作，已保存的内容仍可查看。')
  return (
    <div className={styles.card} role="status">
      <div className={styles.row}>
        <span className={`${styles.dot} ${styles.problem}`} />
        <p className={styles.text}>做题龙还不能开始工作</p>
      </div>
      <p className={styles.guideText}>{message}</p>
      <a className={styles.guideLink} href={setupGuideUrl} target="_blank" rel="noreferrer">
        查看配置教程
      </a>
    </div>
  )
}

/** 书名号内的试卷名不拆行。 */
function Message({ text }: { text: string }) {
  return text.split(/(《[^》]*》)/).map((part, index) =>
    part.startsWith('《') ? (
      <span key={index} className={styles.nowrap}>
        {part}
      </span>
    ) : (
      part
    ),
  )
}

const needsAttention = (task: Task) => task.status === 'failed' || task.status === 'blocked'

function TaskList({ title, items }: { title: string; items: Task[] }) {
  if (items.length === 0) return null
  return (
    <section className={styles.section}>
      <h3>{title}</h3>
      <ul>
        {items.map((task) => (
          <li key={task.id}>
            {task.progress.message}
            {task.error && <span className={styles.problemText}>{task.error}</span>}
            {needsAttention(task) && task.allowed_actions.includes('retry') && (
              <Button size="sm">再试一次</Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** 侧栏底部的后台进度：空闲时不显示；点开查看排队与没有完成的项目。 */
export function BackgroundIndicator() {
  const { data } = useTasks()
  if (!data) return null
  if (data.availability.status === 'unavailable')
    return <SetupGuide availability={data.availability} />
  const { active, queued_count: waiting, failed_count: failed } = data
  if (!active && failed === 0) return null

  return (
    <Popover.Root>
      <Popover.Trigger className={styles.card} aria-label="后台进度，点开查看全部">
        <span className={styles.row}>
          <span className={`${styles.dot} ${active ? '' : styles.problem}`} />
          <span className={styles.text}>
            {active ? (
              <Message text={`做题龙${active.progress.message}`} />
            ) : (
              `有 ${failed} 项没有完成`
            )}
          </span>
        </span>
        {active && (
          <span className={styles.bar}>
            <span />
          </span>
        )}
        <span className={styles.foot}>
          <span>
            {failed > 0
              ? `${failed} 项没有完成`
              : waiting > 0
                ? `还有 ${waiting} 项在等待`
                : '查看详情'}
          </span>
          <ChevronRight size={14} aria-hidden />
        </span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="right" align="end" sideOffset={12} className={styles.popover}>
          <TaskList title="进行中" items={active ? [active] : []} />
          <TaskList title="等待中" items={data.items.filter((task) => task.status === 'queued')} />
          <TaskList title="没有完成" items={data.items.filter(needsAttention)} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
