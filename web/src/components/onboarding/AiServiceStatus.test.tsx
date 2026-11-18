import { QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { TasksResponse } from '../../api/types'
import { createQueryClient } from '../../app/queryClient'
import { tasks } from '../../mocks/data'
import { json, mockServer } from '../../test/server'
import { AiServiceStatus, CHECK_TIMEOUT_MS, resetAutoConnectForTests } from './AiServiceStatus'

type Availability = TasksResponse['availability']

/** 后台：availability 可变；connect 被调用时按 onConnect 改变状态 */
function backend(initial: Availability, onConnect?: () => Availability) {
  let availability = initial
  const connects: number[] = []
  mockServer({
    routes: (path, init) => {
      if (path === '/api/tasks') return json({ ...tasks, active: null, availability })
      if (path === '/api/agent/connect' && init?.method === 'POST') {
        connects.push(Date.now())
        if (onConnect) availability = onConnect()
        return json({ status: 'idle' })
      }
      return undefined
    },
  })
  return {
    connects,
    set: (next: Availability) => {
      availability = next
    },
  }
}

const idleChecking: Availability = { status: 'checking', reason: null, message: '有任务时自动连接' }
const ready: Availability = { status: 'available', reason: null, message: '学习服务可用' }

function renderStatus(count = 1) {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        {Array.from({ length: count }, (_, i) => (
          <section key={i} aria-label={`位置${i}`}>
            <AiServiceStatus />
          </section>
        ))}
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => resetAutoConnectForTests())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('starts a check by itself when the backend has not checked yet, then shows the result', async () => {
  const server = backend(idleChecking, () => ready)
  renderStatus()
  expect(await screen.findByText('已就绪')).toBeInTheDocument()
  expect(server.connects).toHaveLength(1)
})

it('keeps refreshing while checking, without waiting for a push event', async () => {
  // connect 只把状态推进到“连接中”，结果过一会儿才出来
  const server = backend(idleChecking, () => ({ ...idleChecking, message: '正在连接' }))
  renderStatus()
  expect(await screen.findByText('检测中')).toBeInTheDocument()
  await vi.waitFor(() => expect(server.connects).toHaveLength(1))
  // 之后的变化没有任何推送，只能靠“检测中”时的定时刷新拿到
  server.set({ status: 'unavailable', reason: 'not_logged_in', message: '' })
  expect(await screen.findByText('未登录', {}, { timeout: 4000 })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '重新检查' })).toBeInTheDocument()
})

it('gives an answer and a recheck button when checking takes too long', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  // connect 不改变状态：一直“检测中”
  const server = backend(idleChecking)
  renderStatus()
  expect(await screen.findByText('检测中')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '重新检查' })).not.toBeInTheDocument()
  await act(async () => {
    vi.advanceTimersByTime(CHECK_TIMEOUT_MS + 100)
  })
  expect(await screen.findByText('检测时间比较长')).toBeInTheDocument()
  const recheck = screen.getByRole('button', { name: '重新检查' })
  server.set(ready)
  await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(recheck)
  expect(await screen.findByText('已就绪')).toBeInTheDocument()
  expect(server.connects.length).toBe(2)
})

it('shows a result and a recheck button when the check request fails', async () => {
  mockServer({
    routes: (path, init) => {
      if (path === '/api/tasks') return json({ ...tasks, active: null, availability: idleChecking })
      if (path === '/api/agent/connect' && init?.method === 'POST')
        return json({ error: '学习助手尚未初始化' }, 400)
      return undefined
    },
  })
  renderStatus()
  expect(await screen.findByText('学习助手尚未初始化')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '重新检查' })).toBeInTheDocument()
})

it('checks once and shows the same state when onboarding and settings are both open', async () => {
  const server = backend(idleChecking, () => ready)
  renderStatus(2)
  for (const name of ['位置0', '位置1']) {
    expect(
      await within(screen.getByRole('region', { name })).findByText('已就绪'),
    ).toBeInTheDocument()
  }
  expect(server.connects).toHaveLength(1)
})
