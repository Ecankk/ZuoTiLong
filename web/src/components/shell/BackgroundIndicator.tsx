import * as Popover from '@radix-ui/react-popover'
import { ChevronRight } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { endpoints } from '../../api/endpoints'
import { queryKeys, useTasks } from '../../api/queries'
import type { Task, TasksResponse } from '../../api/types'
import { Link } from 'react-router'
import { useConnection } from '../../api/connection'
import { friendlyError } from '../../lib/errors'
import { SETUP_GUIDE_PATH, setupMessage } from '../../lib/setup'
import { Button } from '../ui/Button'
import styles from './BackgroundIndicator.module.css'

function SetupGuide({ availability }: { availability: TasksResponse['availability'] }) {
  const message = setupMessage(availability)
  return (
    <div className={styles.card} role="status">
      <div className={styles.row}>
        <span className={`${styles.dot} ${styles.problem}`} />
        <p className={styles.text}>做题龙还不能开始工作</p>
      </div>
      <p className={styles.guideText}>{message}</p>
      <Link className={styles.guideLink} to={SETUP_GUIDE_PATH}>
        查看配置教程
      </Link>
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

/** 按后端给的 allowed_actions 显示处理按钮：重试，和次要的取消（排队中为“取消等待”）。 */
function TaskButtons({ task }: { task: Task }) {
  const client = useQueryClient()
  const action = useMutation({
    mutationFn: (name: 'retry' | 'cancel') => endpoints.taskAction(task.id, name),
    onSuccess: (summary) => {
      client.setQueryData(queryKeys.tasks, summary)
      void client.invalidateQueries({ queryKey: ['practices'] })
      void client.invalidateQueries({ queryKey: ['papers'] })
    },
  })
  const canRetry = needsAttention(task) && task.allowed_actions.includes('retry')
  const canCancel = task.allowed_actions.includes('cancel')
  if (!canRetry && !canCancel) return null
  return (
    <>
      {canRetry && (
        <Button size="sm" disabled={action.isPending} onClick={() => action.mutate('retry')}>
          再试一次
        </Button>
      )}
      {canCancel && (
        <Button
          size="sm"
          variant="ghost"
          disabled={action.isPending}
          onClick={() => action.mutate('cancel')}
        >
          {task.status === 'queued' ? '取消等待' : '不再处理'}
        </Button>
      )}
      {action.error && <span className={styles.problemText}>{friendlyError(action.error)}</span>}
    </>
  )
}

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
            <TaskButtons task={task} />
          </li>
        ))}
      </ul>
    </section>
  )
}

/** 侧栏底部的后台进度：空闲时不显示；点开查看排队与没有完成的项目。 */
/** 和做题龙的连接断了：不再显示可能过期的任务状态 */
function ConnectionLost() {
  return (
    <div className={styles.card} role="status">
      <div className={styles.row}>
        <span className={`${styles.dot} ${styles.problem}`} />
        <p className={styles.text}>连接中断，正在重连…</p>
      </div>
      <p className={styles.guideText}>请确认做题龙还开着。连上后会自动刷新。</p>
    </div>
  )
}

export function BackgroundIndicator() {
  const { data } = useTasks()
  const connection = useConnection()
  if (connection === 'lost') return <ConnectionLost />
  if (!data) return null
  const { active, queued_count: waiting, failed_count: failed } = data
  const unavailable = data.availability.status === 'unavailable'
  // 未就绪且没有待处理任务时只显示引导
  if (unavailable && waiting === 0 && failed === 0)
    return <SetupGuide availability={data.availability} />
  if (!unavailable && !active && failed === 0 && waiting === 0) return null

  const title = unavailable
    ? '做题龙还不能开始工作'
    : active
      ? null
      : failed > 0
        ? `有 ${failed} 项没有完成`
        : `有 ${waiting} 项在等待`
  return (
    <Popover.Root>
      <Popover.Trigger className={styles.card} aria-label="后台进度，点开查看全部">
        <span className={styles.row}>
          <span className={`${styles.dot} ${active && !unavailable ? '' : styles.problem}`} />
          <span className={styles.text}>
            {title ?? <Message text={`做题龙${active?.progress.message ?? ''}`} />}
          </span>
        </span>
        {active && !unavailable && (
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
          {unavailable && (
            <section className={styles.section}>
              <h3>需要先准备 AI 服务</h3>
              <span className={styles.problemText}>{setupMessage(data.availability)}</span>
              <Link to={SETUP_GUIDE_PATH}>查看配置教程</Link>
            </section>
          )}
          <TaskList title="进行中" items={active ? [active] : []} />
          <TaskList title="等待中" items={data.items.filter((task) => task.status === 'queued')} />
          <TaskList title="没有完成" items={data.items.filter(needsAttention)} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
