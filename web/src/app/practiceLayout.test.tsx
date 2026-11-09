import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { PracticeCard, PracticeGroup } from '../api/types'
import { practiceDetails, practices } from '../mocks/data'
import { buildSections } from '../pages/practice/PracticePage'
import { json, mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

const base = practices.items[0].items[0]
const card = (
  id: string,
  topics: [string, string][],
  status: PracticeCard['status'] = 'pending',
) => ({
  ...base,
  id,
  status,
  // 没做的题没有作答；有作答但还没批改的算“待批改”
  latest_attempt_id: status === 'pending' ? null : base.latest_attempt_id,
  topics: topics.map(([topic_id, name]) => ({ topic_id, name })),
})
const group = (id: string, label: string, items: PracticeCard[]): PracticeGroup => ({
  id,
  label,
  items,
  counts: { pending: 0, grading: 0, graded: 0, needs_supplement: 0, inactive: 0, total: 0 },
})

const shared = card('probe-shared', [
  ['t-exp', '随机变量的期望'],
  ['t-var', '方差及其计算式'],
])
const groups = [
  group('t-exp', '随机变量的期望', [shared, card('probe-a', [['t-exp', '随机变量的期望']])]),
  group('t-var', '方差及其计算式', [shared]),
  group('t-ode', '一阶线性微分方程', [card('probe-b', [['t-ode', '一阶线性微分方程']], 'graded')]),
]

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('lists a practice once and shows its other topics as tags', () => {
  const sections = buildSections(groups, 'topic')
  expect(sections.map((s) => s.group.id)).toEqual(['t-exp', 't-ode'])
  expect(sections[0].rows.map((r) => r.card.id)).toEqual(['probe-shared', 'probe-a'])
  expect(sections[0].rows[0].also.map((t) => t.name)).toEqual(['方差及其计算式'])
})

it('renders the compact list with matching counts, wrapped sources and sectioned feedback', async () => {
  const detail = practiceDetails.find((d) => d.latest_attempt?.assessment) ?? practiceDetails[0]
  mockServer({
    routes: (path) => {
      if (path === '/api/practices')
        return json({ ...practices, items: groups, total: groups.length })
      if (path.startsWith('/api/practices/'))
        return json({
          ...detail,
          practice: { ...detail.practice, id: decodeURIComponent(path.split('/').pop()!) },
        })
      return undefined
    },
  })
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider
        router={createMemoryRouter(routes, { initialEntries: ['/practice?item=probe-shared'] })}
      />
    </QueryClientProvider>,
  )
  const list = await screen.findByRole('complementary', { name: '考点分组' })
  // 三道不同的题：每道只出现一次；只有一道题的考点压成一行，没有折叠按钮；未做数和列表一致
  expect(within(list).getAllByRole('link', { name: /第 \d 道/ })).toHaveLength(2)
  const done = within(list).getByRole('region', { name: '一阶线性微分方程' })
  expect(within(done).getByRole('link', { name: /一阶线性微分方程/ })).toBeInTheDocument()
  expect(within(done).queryByRole('button')).not.toBeInTheDocument()
  const statusFilter = screen.getByRole('group', { name: '按状态筛选' })
  expect(within(statusFilter).getByRole('button', { name: /未做\s*2/ })).toBeInTheDocument()
  expect(within(list).getByText('也属于：方差及其计算式')).toBeInTheDocument()
  expect(within(list).queryByRole('region', { name: '方差及其计算式' })).not.toBeInTheDocument()
  const current = within(list).getByRole('link', { current: true })
  expect(current).toHaveTextContent('第 1 道')
  if (detail.latest_attempt?.assessment) {
    expect(await screen.findByRole('region', { name: '结论' })).toBeInTheDocument()
    expect(screen.queryByText('首个错误', { selector: 'h4' })).not.toBeInTheDocument()
  }
})
