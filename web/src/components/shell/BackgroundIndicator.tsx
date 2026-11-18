import * as Popover from '@radix-ui/react-popover'
import { Check, ChevronRight } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
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

/**
 * 任务的业务错误原样来自后端。少数固定句子带了开发说法（如“会话”），换成学生看得懂的话；
 * 其余中文原样显示，非中文的不显示原文。
 */
export function taskErrorText(error: string | null) {
  if (!error) return null
  if (error.startsWith('执行已中断'))
    return '上次处理被打断了（比如做题龙中途关闭）。可以再试一次，会从头重新处理。'
  return /[一-鿿]/.test(error) ? error : '这一项没有完成，可以再试一次。'
}

/** 每隔一段时间刷新一次“现在”，只在有进行中的任务时走 */
function useNow(active: boolean, intervalMs = 30_000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const tick = () => setNow(Date.now())
    const first = window.setTimeout(tick, 0)
    const timer = window.setInterval(tick, intervalMs)
    return () => {
      window.clearTimeout(first)
      window.clearInterval(timer)
    }
  }, [active, intervalMs])
  return now
}

/**
 * 从任务提交（created_at）到现在过了多久。接口不给完成比例，
 * 只用这个让人知道“还在进行”，不猜还要多久。
 */
export function elapsedText(createdAt: string, now: number) {
  const started = Date.parse(createdAt)
  if (Number.isNaN(started)) return null
  const minutes = Math.floor((now - started) / 60_000)
  if (minutes < 1) return '刚开始'
  if (minutes < 60) return `已过 ${minutes} 分钟`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `已过 ${hours} 小时 ${rest} 分钟` : `已过 ${hours} 小时`
}

/** 进行了这么久以后，补一句“慢是正常的” */
const LONG_WAIT_MINUTES = 3

/**
 * 进行中的任务结束后，如果它在列表里是“已完成”，短暂显示一张完成卡片再收起；
 * 失败的会直接进“没有完成”，不需要这张卡。
 */
const DONE_VISIBLE_MS = 5000

function useJustCompleted(data: TasksResponse | undefined) {
  const previous = useRef<string | null>(null)
  const [done, setDone] = useState<Task | null>(null)
  const activeId = data?.active?.id ?? null
  useEffect(() => {
    const last = previous.current
    previous.current = activeId
    if (!last || last === activeId || !data) return
    const finished = data.items.find((task) => task.id === last && task.status === 'completed')
    if (finished) setDone(finished)
  }, [activeId, data])
  useEffect(() => {
    if (!done) return
    const timer = window.setTimeout(() => setDone(null), DONE_VISIBLE_MS)
    return () => window.clearTimeout(timer)
  }, [done])
  return activeId ? null : done
}

function DoneCard({ task }: { task: Task }) {
  return (
    <div className={`${styles.card} ${styles.done}`} role="status">
      <span className={styles.row}>
        <span className={styles.doneIcon} aria-hidden>
          <Check size={12} strokeWidth={3} />
        </span>
        <span className={styles.text}>
          <Message text={task.progress.message} />
        </span>
      </span>
    </div>
  )
}

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
          {action.isPending && action.variables === 'retry' ? '正在重新开始…' : '再试一次'}
        </Button>
      )}
      {canCancel && (
        <Button
          size="sm"
          variant="ghost"
          disabled={action.isPending}
          onClick={() => action.mutate('cancel')}
        >
          {action.isPending && action.variables === 'cancel'
            ? '正在取消…'
            : task.status === 'queued'
              ? '取消等待'
              : '不再处理'}
        </Button>
      )}
      {action.error && <span className={styles.problemText}>{friendlyError(action.error)}</span>}
    </>
  )
}

function TaskList({ title, items, now }: { title: string; items: Task[]; now?: number }) {
  if (items.length === 0) return null
  return (
    <section className={styles.section}>
      <h3>{title}</h3>
      <ul>
        {items.map((task) => (
          <li key={task.id}>
            {task.progress.message}
            {now !== undefined && task.status === 'running' && (
              <RunningNote task={task} now={now} />
            )}
            {task.error && <span className={styles.problemText}>{taskErrorText(task.error)}</span>}
            <TaskButtons task={task} />
          </li>
        ))}
      </ul>
    </section>
  )
}

/** 进行中任务的用时，以及等久了的安慰话 */
function RunningNote({ task, now }: { task: Task; now: number }) {
  const elapsed = elapsedText(task.created_at, now)
  const long = (now - Date.parse(task.created_at)) / 60_000 >= LONG_WAIT_MINUTES
  return (
    <span className={styles.problemText}>
      {elapsed && `${elapsed}。`}
      {long
        ? '有的任务要十几分钟，慢一些是正常的。可以先做别的，完成后这里会提示。'
        : '可以先做别的，完成后这里会提示。'}
    </span>
  )
}

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

/** 侧栏底部的后台进度：空闲时不显示；点开查看排队与没有完成的项目。 */
export function BackgroundIndicator() {
  const { data } = useTasks()
  const connection = useConnection()
  const running = Boolean(data?.active) && data?.availability.status !== 'unavailable'
  const now = useNow(running)
  const justDone = useJustCompleted(data)
  const popoverRef = useRef<HTMLDivElement>(null)
  if (connection === 'lost') return <ConnectionLost />
  if (!data) return null
  const { active, queued_count: waiting, failed_count: failed } = data
  const unavailable = data.availability.status === 'unavailable'
  // 未就绪且没有待处理任务时只显示引导
  if (unavailable && waiting === 0 && failed === 0)
    return <SetupGuide availability={data.availability} />
  if (!unavailable && !active && failed === 0 && waiting === 0)
    return justDone ? <DoneCard task={justDone} /> : null
  const elapsed = running && active ? elapsedText(active.created_at, now) : null
  // 标题是“有 N 项没有完成/在等待”时，数量不在底部再说一遍
  const countsInFoot = Boolean(active) || unavailable

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
            {/* 标题已经说过的数量不在底部重复；只剩下一步“点开处理” */}
            {[
              elapsed,
              countsInFoot && failed > 0
                ? `${failed} 项没有完成`
                : countsInFoot && waiting > 0
                  ? `还有 ${waiting} 项在等待`
                  : null,
            ]
              .filter(Boolean)
              .join(' · ') || (failed > 0 && !unavailable ? '点开看看怎么处理' : '查看详情')}
          </span>
          <ChevronRight size={14} aria-hidden />
        </span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="right"
          align="end"
          sideOffset={12}
          className={styles.popover}
          tabIndex={-1}
          // 打开时焦点放在浮层本身，不直接落到“取消等待/再试一次”上，免得一按回车就执行
          ref={popoverRef}
          onOpenAutoFocus={(event) => {
            event.preventDefault()
            popoverRef.current?.focus()
          }}
        >
          {unavailable && (
            <section className={styles.section}>
              <h3>需要先准备 AI 服务</h3>
              <span className={styles.problemText}>{setupMessage(data.availability)}</span>
              <Link to={SETUP_GUIDE_PATH}>查看配置教程</Link>
            </section>
          )}
          <TaskList title="进行中" items={active ? [active] : []} now={running ? now : undefined} />
          <TaskList title="等待中" items={data.items.filter((task) => task.status === 'queued')} />
          <TaskList title="没有完成" items={data.items.filter(needsAttention)} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
