import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

function renderAt(path: string) {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />
    </QueryClientProvider>,
  )
}

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('asks to check the question numbers before analysis and starts it after confirming', async () => {
  const fetch = mockServer()
  renderAt('/papers/paper-fresh')
  const step = await screen.findByRole('region', { name: '核对切题' })
  expect(within(step).getByText('做题龙找到了 3 道题，先核对一下题号')).toBeInTheDocument()
  expect(await within(step).findByRole('button', { name: '纠正题号' })).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: '正误分布' })).not.toBeInTheDocument()
  await userEvent.click(within(step).getByRole('button', { name: /题号没问题，开始分析/ }))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByText(/AI 服务/)).toBeInTheDocument()
  await userEvent.click(within(dialog).getByRole('button', { name: '开始分析' }))
  const call = fetch.mock.calls.find(([url]) => String(url).includes('/analyze'))
  expect(String(call?.[0])).toBe('/api/papers/paper-fresh/analyze')
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ confirmed: true })
})

it('does not show the step for an analysed paper', async () => {
  mockServer()
  renderAt('/papers/paper-2026-1')
  expect(await screen.findByRole('region', { name: '正误分布' })).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: '核对切题' })).not.toBeInTheDocument()
})

it('starts the first analysis from the analysis card with confirmed:true', async () => {
  const fetch = mockServer()
  const original = fetch.getMockImplementation()!
  // 题号还没建立（共 0 题）时不显示核对切题，分析卡片直接给出“开始分析”
  fetch.mockImplementation(async (input, init) => {
    const response = await original(input, init)
    if (String(input) !== '/api/papers/paper-fresh') return response
    const data = await response.json()
    const paper = { ...data.paper, counts: { ...data.paper.counts, total: 0 } }
    return new Response(JSON.stringify({ ...data, paper }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  renderAt('/papers/paper-fresh')
  const card = await screen.findByRole('region', { name: '分析' })
  await userEvent.click(within(card).getByRole('button', { name: '开始分析' }))
  await userEvent.click(await screen.findByRole('button', { name: '确认开始分析' }))
  const call = fetch.mock.calls.find(([url]) => String(url).includes('/analyze'))
  expect(String(call?.[0])).toBe('/api/papers/paper-fresh/analyze')
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ confirmed: true })
})
