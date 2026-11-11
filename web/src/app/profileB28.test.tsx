import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { Overview } from '../api/types'
import { overview, periodOverview, periodTrends } from '../mocks/profile'
import { json, mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

function renderAt(path: string, data: Overview) {
  mockServer({
    routes: (p) => {
      if (p === '/api/profile/overview') return json(data)
      if (p === '/api/profile/trends') return json(periodTrends)
      return undefined
    },
  })
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

const spot = (region: HTMLElement, name: string) => within(region).getByText(name).closest('li')!

it('separates recent weak spots from older papers and states lost points honestly', async () => {
  renderAt('/profile', periodOverview)
  const weak = await screen.findByRole('region', { name: '最该补的地方' })
  expect(weak).toHaveTextContent('近期记录较少，以下包含历史卷依据')
  expect(weak).not.toHaveTextContent('按近 28 天的错题排序')

  const recent = spot(weak, '随机变量的数字特征')
  expect(recent).toHaveTextContent('涉及原卷失分约 7 分（按已保存估分）')
  // 依据句已写了做几道、错几道，不再重复计数，只补考点数
  expect(recent).toHaveTextContent('3 个考点要补')
  expect(recent).not.toHaveTextContent('原卷错')
  expect(recent).not.toHaveTextContent('更早的试卷')

  const older = spot(weak, '特征值与特征向量')
  expect(older).toHaveTextContent('更早的试卷')
  expect(older).toHaveTextContent('涉及原卷失分约 14 分（按已保存估分，另有 1 道分数未知）')
  expect(older).toHaveTextContent('近 28 天没有这一章的错题')
  // 没有依据句时显示原卷错题数
  expect(older).toHaveTextContent('原卷错 3 道 · 3 个考点要补')
  // 错题按作答日期的精度显示
  const evidence = within(older).getByRole('list', { name: '特征值与特征向量的错题' })
  expect(evidence).toHaveTextContent('约2026年3月')
  expect(evidence).toHaveTextContent('记不清')
  // 练习错题用作答时间显示日期
  expect(within(recent).getByRole('link', { name: /方差及其计算式/ })).toHaveTextContent(
    '2026年11月6日',
  )

  // 失分未知时不写 0 分
  const unknown = spot(weak, '重积分')
  expect(unknown).toHaveTextContent('涉及的原卷失分：分数未知')
  expect(unknown).not.toHaveTextContent('0 分')
  // 各章失分不相加：页面上不出现 7+14 的合计
  expect(document.body.textContent).not.toMatch(/21 分/)
  expect(document.body.textContent).not.toMatch(/undefined|null|NaN|证据|精度|桶/)
})

it('shows the first-error card only when the backend gives a summary', async () => {
  renderAt('/profile', periodOverview)
  const card = await screen.findByRole('region', { name: '最常错在哪一步' })
  expect(card).toHaveTextContent('近 28 天 8 道错题里，有 4 道最先错在计算这一步。')
  const links = within(card).getAllByRole('link')
  expect(links).toHaveLength(3)
  expect(links[0]).toHaveAttribute('href', '/papers/paper-2021/questions/9')
  expect(links[1]).toHaveAttribute('href', '/practice?item=probe-var-2')
  expect(links[0]).toHaveTextContent('第 9 题先错在计算')
})

it('uses the evidence label in the first-error card when the backend gives one', async () => {
  const summary = periodOverview.first_error_summary!
  renderAt('/profile', {
    ...periodOverview,
    first_error_summary: {
      ...summary,
      evidence: summary.evidence.map((e, i) =>
        i === 0 ? { ...e, label: '《2021数学一》第9题' } : e,
      ),
    },
  })
  const card = await screen.findByRole('region', { name: '最常错在哪一步' })
  expect(within(card).getAllByRole('link')[0]).toHaveTextContent('《2021数学一》第9题先错在计算')
})

it('hides the first-error card when the summary is null', async () => {
  renderAt('/profile', { ...overview, first_error_summary: null })
  await screen.findByRole('region', { name: '最该补的地方' })
  expect(screen.queryByRole('region', { name: '最常错在哪一步' })).not.toBeInTheDocument()
})

it('notes attempts whose date is only a month or unknown in the weekly trend', async () => {
  renderAt('/profile', periodOverview)
  await userEvent.click(await screen.findByRole('button', { name: /每周作答趋势/ }))
  expect(
    await screen.findByText('另有 13 次作答的日期只到月份或记不清，没算进每周统计。'),
  ).toBeInTheDocument()
})

it('home weak spots use the same period wording and wrong counts', async () => {
  renderAt('/', periodOverview)
  const weak = await screen.findByRole('region', { name: '最该补的地方' })
  expect(weak).toHaveTextContent('近期记录较少，以下包含历史卷依据')
  const rows = within(weak)
    .getAllByRole('link')
    .filter((a) => a.querySelector('strong'))
  expect(rows[0]).toHaveTextContent('涉及原卷失分约 7 分（按已保存估分）')
  expect(rows[0]).toHaveTextContent('错 4 道')
  expect(rows[1]).toHaveTextContent('更早的试卷 · 涉及原卷失分约 14 分')
  expect(rows[1]).toHaveTextContent('错 3 道')
  expect(screen.getByRole('region', { name: '最常错在哪一步' })).toBeInTheDocument()
})
