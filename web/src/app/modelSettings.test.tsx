import { QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CHECK_AGAIN_MS } from '../api/queries'
import type { AgentModels } from '../api/types'
import { agentModels, preferences } from '../mocks/data'
import { mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

function renderSettings() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/settings'] })} />
    </QueryClientProvider>,
  )
}

const posts = (fetch: ReturnType<typeof mockServer>) =>
  fetch.mock.calls
    .filter(([url, init]) => String(url) === '/api/preferences' && init?.method === 'POST')
    .map(([, init]) => JSON.parse(String(init?.body)))

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('switches a model, moves to the closest effort and saves only that tier', async () => {
  const fetch = mockServer()
  renderSettings()
  const card = await screen.findByRole('region', { name: 'AI 模型与思考深度' })
  const model = await within(card).findByRole('combobox', { name: '判断类任务用的模型' })
  const effort = within(card).getByRole('combobox', { name: '判断类任务的思考深度' })
  await vi.waitFor(() => expect(model).toBeEnabled())
  expect(effort).toHaveDisplayValue('非常仔细')
  expect(within(card).getByRole('combobox', { name: '整理类任务的思考深度' })).toHaveDisplayValue(
    '仔细',
  )
  expect(
    within(card).queryByText(/execution_profiles|judgment|xhigh|reasoning/),
  ).not.toBeInTheDocument()

  await userEvent.selectOptions(model, 'gpt-6-swift')
  expect(effort).toHaveDisplayValue('快速')
  expect(within(card).getByText(/没有“非常仔细”这一档，已改为“快速”/)).toBeInTheDocument()

  await userEvent.click(within(card).getByRole('button', { name: '保存' }))
  expect(await within(card).findByText('已保存，下一个任务起生效')).toBeInTheDocument()
  expect(posts(fetch)).toEqual([
    { execution_profiles: { judgment: { model: 'gpt-6-swift', effort: 'low' } } },
  ])

  await userEvent.click(within(card).getByRole('button', { name: '恢复默认' }))
  expect(await within(card).findByText('已恢复默认，下一个任务起生效')).toBeInTheDocument()
  expect(posts(fetch)[1]).toEqual({ execution_profiles: null })
  expect(model).toHaveDisplayValue('GPT-6 Luna')
})

it('marks a saved model this computer does not have instead of replacing it', async () => {
  mockServer({
    preferences: {
      ...preferences,
      execution_profiles: {
        judgment: { model: 'gpt-5-old', effort: 'xhigh' },
        organization: { model: 'gpt-6-luna-mini', effort: 'xhigh' },
      },
    },
  })
  renderSettings()
  const card = await screen.findByRole('region', { name: 'AI 模型与思考深度' })
  const model = await within(card).findByRole('combobox', { name: '判断类任务用的模型' })
  await vi.waitFor(() => expect(within(card).getAllByRole('alert')).toHaveLength(2))
  expect(model).toHaveDisplayValue('gpt-5-old')
  expect(within(card).getAllByText(/这台电脑上用不了这个模型/)).toHaveLength(2)
})

it('explains why models cannot be chosen and disables the choices', async () => {
  mockServer({
    agentModels: [
      { status: 'unavailable', reason: 'not_logged_in', message: 'not logged in', items: [] },
    ],
  })
  renderSettings()
  const card = await screen.findByRole('region', { name: 'AI 模型与思考深度' })
  expect(await within(card).findByText('AI 服务还没有登录，暂时不能选择模型')).toBeInTheDocument()
  expect(within(card).getByRole('combobox', { name: '判断类任务用的模型' })).toBeDisabled()
  expect(within(card).getByRole('button', { name: '保存' })).toBeDisabled()
})

it('reads the model list again while it is still being checked', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const checking: AgentModels = { status: 'checking', reason: null, message: '', items: [] }
  const fetch = mockServer({ agentModels: [checking, agentModels] })
  renderSettings()
  const card = await screen.findByRole('region', { name: 'AI 模型与思考深度' })
  expect(await within(card).findByText('正在读取这台电脑上可用的模型')).toBeInTheDocument()
  expect(within(card).getByRole('combobox', { name: '整理类任务用的模型' })).toBeDisabled()
  await act(() => vi.advanceTimersByTimeAsync(CHECK_AGAIN_MS + 100))
  await vi.waitFor(() =>
    expect(within(card).getByRole('combobox', { name: '整理类任务用的模型' })).toBeEnabled(),
  )
  const reads = fetch.mock.calls.filter(([url]) => String(url) === '/api/agent/models')
  expect(reads).toHaveLength(2)
})

it('never shows the raw backend message when models are unavailable', async () => {
  mockServer({
    agentModels: [{ status: 'unavailable', reason: 'other', message: 'spawn ENOENT', items: [] }],
  })
  renderSettings()
  const card = await screen.findByRole('region', { name: 'AI 模型与思考深度' })
  expect(await within(card).findByText('暂时读不到可用的模型')).toBeInTheDocument()
  expect(card.textContent).not.toMatch(/ENOENT/)
})

it('groups a long model list by name and lets the student search it', async () => {
  const many = [
    'gpt-6-a',
    'gpt-6-b',
    'gpt-6-c',
    'gpt-5.1-a',
    'gpt-5.1-b',
    'o3',
    'o3-mini',
    'local-qwen',
  ]
  const items = [
    ...agentModels.items,
    ...many.map((name) => ({ id: name, name, efforts: ['low', 'high'] })),
  ]
  mockServer({ agentModels: [{ ...agentModels, items }] })
  renderSettings()
  const card = await screen.findByRole('region', { name: 'AI 模型与思考深度' })
  const model = await within(card).findByRole('combobox', { name: '判断类任务用的模型' })
  await vi.waitFor(() => expect(model).toBeEnabled())
  expect(model.querySelectorAll('optgroup').length).toBeGreaterThan(1)
  const search = within(card).getByRole('searchbox', { name: '搜索判断类任务用的模型' })
  await userEvent.type(search, 'o3')
  const names = [...model.querySelectorAll('option')].map((o) => o.textContent)
  expect(names).toContain('o3-mini')
  expect(names).not.toContain('gpt-6-b')
})
