import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { Task, TasksResponse } from '../api/types'
import { tasks } from '../mocks/data'
import { mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const task = (change: Partial<Task>): Task => ({ ...tasks.items[0], ...change })
const summary = (items: Task[], change: Partial<TasksResponse> = {}): TasksResponse => ({
  ...tasks,
  items,
  total: items.length,
  active: null,
  queued_count: items.filter((t) => t.status === 'queued').length,
  failed_count: items.filter((t) => t.status === 'failed').length,
  ...change,
})

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('offers cancel next to retry when the task allows it', async () => {
  const failed = task({
    id: 'job-failed',
    kind: 'grade_attempt',
    status: 'failed',
    progress: { message: '批改没有完成' },
    error: '作答照片读不出来',
    allowed_actions: ['retry', 'cancel'],
  })
  const fetch = mockServer({ tasks: summary([failed]) })
  renderAt('/')
  await userEvent.click(await screen.findByRole('button', { name: '后台进度，点开查看全部' }))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByRole('button', { name: '再试一次' })).toBeInTheDocument()
  await userEvent.click(within(dialog).getByRole('button', { name: '不再处理' }))
  const call = fetch.mock.calls.find(([url]) => String(url).includes('/action'))
  expect(String(call?.[0])).toBe('/api/tasks/job-failed/action')
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ action: 'cancel' })
})

it('does not call a queued practice selection an analysis', async () => {
  const selecting = task({
    id: 'job-select',
    kind: 'prepare_practice',
    status: 'queued',
    progress: { message: '等待为《2023 数学一》准备练习' },
    allowed_actions: ['cancel'],
  })
  mockServer({ tasks: summary([selecting]) })
  renderAt('/papers/paper-2023-1')
  const card = await screen.findByRole('region', { name: '分析' })
  expect(await within(card).findByText(/已开始准备练习/)).toBeInTheDocument()
  expect(within(card).queryByText(/分析已排队/)).not.toBeInTheDocument()
})

it('finds a topic by alias and filters the current collection by it', async () => {
  const fetch = mockServer()
  const router = renderAt('/bank')
  const input = await screen.findByRole('searchbox', { name: '搜索考点或题面' })
  expect(input).toHaveAttribute('placeholder', '在真题里搜考点或题面文字')
  await userEvent.click(input)
  await userEvent.type(input, '代换')
  const results = await screen.findByRole('group', { name: '搜索建议' })
  await userEvent.click(await within(results).findByRole('button', { name: /等价无穷小替换/ }))
  expect(router.state.location.search).toContain('topic=a1')
  await vi.waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([url]) => String(url).includes('collection=zhenti') && String(url).includes('topic_id=a1'),
      ),
    ).toBe(true),
  )
})
