import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { DataStatus, TasksResponse } from '../../api/types'
import { createQueryClient } from '../../app/queryClient'
import { routes } from '../../app/routes'
import { tasks } from '../../mocks/data'
import { json, mockServer } from '../../test/server'

const status = (last: string | null): DataStatus => ({
  data_dir: 'C:\\data\\workspaces\\default',
  library_dir: 'C:\\data\\library',
  library_exists: true,
  library_env_override: false,
  databases: {
    learning: { bytes: 800_000, exists: true },
    library: { bytes: 380_000, exists: true },
    session: { bytes: 8_000, exists: true },
  },
  invalid_file_references: { count: 0, examples: [] },
  last_backup_at: last,
  path_migration: {
    pending: false,
    ready_count: 0,
    unresolved_count: 0,
    historical_reference_count: 0,
    plan_sha256: '',
  },
})

/** reply：备份接口的回应；成功时同时把“最近备份”和备份列表更新 */
function server({
  reply = 'ok',
  taskState = { ...tasks, active: null },
}: {
  reply?: 'ok' | 'busy' | 'error' | 'slow'
  taskState?: TasksResponse
} = {}) {
  let last: string | null = null
  let list: { name: string; bytes: number }[] = []
  const posts: string[] = []
  let release: () => void = () => {}
  mockServer({
    tasks: taskState,
    routes: (path, init) => {
      if (path === '/api/data/status') return json(status(last))
      if (path === '/api/maintenance/backups') return json({ backups: list })
      if (path === '/api/maintenance/backup' && init?.method === 'POST') {
        posts.push(path)
        if (reply === 'busy') return json({ error: '请等待当前任务交付或停止后重试' }, 409)
        if (reply === 'error') return json({ error: 'disk full' }, 500)
        const succeed = () => {
          last = '2026-11-18T18:30:47+00:00'
          list = [{ name: 'mathlens-personal-20261118.zip', bytes: 7_657_131 }]
          return json({ path: 'backups/x.zip', files: 18, retention_count: 3, removed: [] })
        }
        if (reply === 'slow') return new Promise<Response>((r) => (release = () => r(succeed())))
        return succeed()
      }
      return undefined
    },
  })
  return { posts, release: () => release() }
}

function renderSettings() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/settings'] })} />
    </QueryClientProvider>,
  )
}

const card = () => screen.findByRole('region', { name: '数据与备份' })

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('shows progress, then success with the time, and refreshes 最近备份', async () => {
  const backend = server({ reply: 'slow' })
  renderSettings()
  const region = await card()
  expect(await within(region).findByText('还没有备份')).toBeInTheDocument()
  await userEvent.click(within(region).getByRole('button', { name: '立即备份' }))
  expect(await within(region).findByText('正在备份，请稍等…')).toBeInTheDocument()
  expect(within(region).getByRole('button', { name: '正在备份…' })).toBeDisabled()
  backend.release()
  expect(await within(region).findByText(/备份好了：.*共 18 个文件/)).toBeInTheDocument()
  expect(within(region).queryByText('还没有备份')).not.toBeInTheDocument()
  expect(await within(region).findByText('1 份')).toBeInTheDocument()
  expect(backend.posts).toHaveLength(1)
})

it('explains a refusal while a task is running instead of saying “stop and retry”', async () => {
  server({ reply: 'busy' })
  renderSettings()
  const region = await card()
  await userEvent.click(await within(region).findByRole('button', { name: '立即备份' }))
  const alert = await within(region).findByRole('alert')
  expect(alert).toHaveTextContent('没能备份')
  expect(alert).toHaveTextContent('正在处理任务')
  expect(alert).not.toHaveTextContent('停止')
  expect(within(region).getByText('还没有备份')).toBeInTheDocument()
})

it('shows other failures clearly', async () => {
  server({ reply: 'error' })
  renderSettings()
  const region = await card()
  await userEvent.click(await within(region).findByRole('button', { name: '立即备份' }))
  expect(await within(region).findByRole('alert')).toHaveTextContent('没能备份')
})

it('says up front that backup waits while a task is running', async () => {
  const backend = server({ taskState: tasks }) // 默认 mock 有正在运行的任务
  renderSettings()
  const region = await card()
  expect(await within(region).findByText(/这时不能备份/)).toBeInTheDocument()
  expect(within(region).getByRole('button', { name: '立即备份' })).toBeDisabled()
  expect(backend.posts).toHaveLength(0)
})
