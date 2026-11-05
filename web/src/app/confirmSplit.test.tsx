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
  expect(within(dialog).getByText(/Codex/)).toBeInTheDocument()
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
