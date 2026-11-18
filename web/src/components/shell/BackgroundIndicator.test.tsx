import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { queryKeys } from '../../api/queries'
import type { Task, TasksResponse } from '../../api/types'
import { tasks } from '../../mocks/data'
import { BackgroundIndicator, elapsedText } from './BackgroundIndicator'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString()

function renderTray(initial: TasksResponse) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
  client.setQueryData(queryKeys.tasks, initial)
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(initial), { status: 200 })),
  )
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BackgroundIndicator />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return client
}

const running = (change: Partial<Task> = {}): Task => ({
  ...tasks.items[0],
  status: 'running',
  ...change,
})

const summary = (items: Task[], active: Task | null): TasksResponse => ({
  ...tasks,
  items,
  total: items.length,
  active,
  queued_count: items.filter((t) => t.status === 'queued').length,
  failed_count: 0,
})

it('describes elapsed time without guessing how long is left', () => {
  const now = Date.parse('2026-11-17T10:00:00Z')
  expect(elapsedText('2026-11-17T09:59:40Z', now)).toBe('刚开始')
  expect(elapsedText('2026-11-17T09:48:00Z', now)).toBe('已过 12 分钟')
  expect(elapsedText('2026-11-17T08:30:00Z', now)).toBe('已过 1 小时 30 分钟')
  expect(elapsedText('not a date', now)).toBeNull()
})

it('shows how long the running task has been going', async () => {
  const task = running({ created_at: minutesAgo(12) })
  renderTray(summary([task], task))
  const trigger = await screen.findByRole('button', { name: '后台进度，点开查看全部' })
  expect(trigger).toHaveTextContent('做题龙正在分析《2023 数学一》')
  expect(trigger).toHaveTextContent('已过 12 分钟')
})

it('briefly confirms a finished task, then goes away', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const task = running({ created_at: minutesAgo(2) })
  const client = renderTray(summary([task], task))
  expect(await screen.findByRole('button', { name: '后台进度，点开查看全部' })).toBeInTheDocument()
  const finished: Task = {
    ...task,
    status: 'completed',
    progress: { message: '分析试卷《2023 数学一》已完成' },
  }
  act(() => client.setQueryData(queryKeys.tasks, summary([finished], null)))
  expect(await screen.findByRole('status')).toHaveTextContent('分析试卷《2023 数学一》已完成')
  act(() => vi.advanceTimersByTime(5100))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

it('says the failed count once, explains an interrupted run, and does not focus a button on open', async () => {
  const failed = running({
    id: 'job-f',
    status: 'failed',
    progress: { message: '分析试卷《2023 数学一》需要处理' },
    error: '执行已中断；重试将在新会话重新执行',
    allowed_actions: ['retry', 'cancel'],
  })
  renderTray({ ...summary([failed], null), failed_count: 1 })
  const trigger = await screen.findByRole('button', { name: '后台进度，点开查看全部' })
  expect(trigger.textContent?.match(/1 项没有完成/g)).toHaveLength(1)
  expect(trigger).toHaveTextContent('点开看看怎么处理')
  await userEvent.click(trigger)
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('上次处理被打断了')
  expect(dialog).not.toHaveTextContent('会话')
  expect(within(dialog).getByRole('button', { name: '再试一次' })).not.toHaveFocus()
})
