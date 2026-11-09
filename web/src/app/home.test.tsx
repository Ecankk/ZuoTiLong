import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { PracticeGroup } from '../api/types'
import { practices, tasks } from '../mocks/data'
import { greeting } from '../pages/home/HomePage'
import { json, mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

function renderHome() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/'] })} />
    </QueryClientProvider>,
  )
}

const base = practices.items[0].items[0]
const manyGroups: PracticeGroup[] = Array.from({ length: 8 }, (_, i) => ({
  id: `t${i}`,
  label: `考点 ${i + 1}`,
  counts: practices.items[0].counts,
  items: [
    {
      ...base,
      id: `p${i}`,
      status: 'pending',
      topics: [{ topic_id: `t${i}`, name: `考点 ${i + 1}` }],
    },
  ],
}))

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('greets late-night users without saying good morning', () => {
  expect(greeting(new Date(2026, 10, 10, 2, 42))).toBe('夜深了，早点休息')
  expect(greeting(new Date(2026, 10, 10, 7, 0))).toBe('早上好')
  expect(greeting(new Date(2026, 10, 10, 20, 0))).toBe('晚上好')
})

it('leads with continuing practice, caps the topic list and shows a slim AI banner', async () => {
  mockServer({
    tasks: {
      ...tasks,
      availability: { status: 'unavailable', reason: 'disabled', message: '学习服务未启用' },
    },
    routes: (path) =>
      path === '/api/practices'
        ? json({ ...practices, items: manyGroups, total: manyGroups.length })
        : undefined,
  })
  renderHome()
  const main = await screen.findByRole('region', { name: '现在做什么' })
  expect(within(main).getByRole('heading', { name: /“考点 1” 还有 1 道没做/ })).toBeInTheDocument()
  expect(within(main).getByRole('link', { name: /继续做/ })).toHaveAttribute(
    'href',
    '/practice?item=p0',
  )
  const topics = screen.getByRole('region', { name: '待练的考点' })
  expect(within(topics).getAllByRole('listitem')).toHaveLength(5)
  expect(within(topics).getByRole('link', { name: '还有 3 个考点 · 去练习 →' })).toHaveAttribute(
    'href',
    '/practice',
  )
  const banner = screen.getByRole('status', { name: '' })
  expect(banner).toHaveTextContent('学习服务现在没有启用')
  expect(screen.queryByText('学习服务未启用')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: '查看准备步骤' })).toHaveAttribute('href', '/help/setup')
})

it('offers new papers, the bank and the profile when everything is done', async () => {
  mockServer({
    routes: (path) =>
      path === '/api/practices'
        ? json({ ...practices, items: [], total: 0, counts: { ...practices.counts, pending: 0 } })
        : undefined,
  })
  renderHome()
  const main = await screen.findByRole('region', { name: '现在做什么' })
  expect(within(main).getByRole('link', { name: /上传新试卷/ })).toHaveAttribute('href', '/papers')
  expect(within(main).getByRole('link', { name: '在题库里挑题' })).toHaveAttribute('href', '/bank')
  expect(within(main).getByRole('link', { name: '看完整画像' })).toHaveAttribute('href', '/profile')
})

it('shows a retry card instead of a blank page when the server is unreachable', async () => {
  mockServer({
    routes: (path) => {
      if (path === '/api/practices') throw new TypeError('Failed to fetch')
      return undefined
    },
  })
  renderHome()
  expect(await screen.findByRole('alert', {}, { timeout: 4000 })).toHaveTextContent('连不上做题龙')
  expect(document.body.textContent).not.toMatch(/Failed to fetch/)
})
