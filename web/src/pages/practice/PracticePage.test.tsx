import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { PracticeCard, PracticeGroup, PracticeResponse } from '../../api/types'
import { createQueryClient } from '../../app/queryClient'
import { routes } from '../../app/routes'
import { practiceDetails, practices } from '../../mocks/data'
import { json, mockServer } from '../../test/server'

const base = practices.items[0].items[0]
const graded = practiceDetails[0]
const card = (
  id: string,
  topic: [string, string],
  status: PracticeCard['status'] = 'pending',
  extra: Record<string, unknown> = {},
): PracticeCard => ({
  ...base,
  id,
  status,
  latest_attempt_id: status === 'pending' ? null : `attempt-${id}`,
  topics: [{ topic_id: topic[0], name: topic[1] }],
  ...extra,
})
const group = (id: string, label: string, items: PracticeCard[]): PracticeGroup => ({
  id,
  label,
  items,
  counts: { pending: 0, grading: 0, graded: 0, needs_supplement: 0, inactive: 0, total: 0 },
})

const exp: [string, string] = ['t-exp', '随机变量的期望']
const mle: [string, string] = ['t-mle', '参数估计']
const cp: [string, string] = ['t-cp', '条件概率']
const groups = [
  group('t-exp', '随机变量的期望', [card('p-a', exp), card('p-b', exp)]),
  group('t-mle', '参数估计', [card('p-graded', mle, 'graded')]),
  group('t-cp', '条件概率', [card('p-profile', cp, 'pending', { origin: 'profile' })]),
]

/** 已批改练习：旧图片题的导航文字、“参考解析见原图”占位、两段结论 */
const gradedDetail: PracticeResponse = {
  ...graded,
  practice: groups[1].items[0],
  question: {
    question_text: '2018 数学一 第15题 · 参数估计',
    question_image: '/api/bank/x/question',
    analysis_text: '参考解析见原图',
    expected: '$\\frac12$',
  },
  latest_attempt: {
    ...graded.latest_attempt!,
    assessment: {
      ...graded.latest_attempt!.assessment!,
      feedback: '思路对了，最后一步算错了系数\n事后批改：未见事后批改痕迹。',
    },
  },
}

function detailFor(id: string): PracticeResponse {
  if (id === 'p-graded') return gradedDetail
  const found = groups.flatMap((g) => g.items).find((c) => c.id === id)!
  return {
    ...practiceDetails[1],
    practice: found,
    question: { question_text: '求 $E(X)$。' },
    actions: ['submit'],
  }
}

function renderAt(path: string) {
  mockServer({
    routes: (url) => {
      if (url === '/api/practices') return json({ ...practices, items: groups, total: 3 })
      const match = url.match(/^\/api\/practices\/([^/]+)$/)
      if (match) return json(detailFor(decodeURIComponent(match[1])))
      return undefined
    },
  })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('filters the list by status and shows counts that match', async () => {
  const router = renderAt('/practice')
  const statusFilter = await screen.findByRole('group', { name: '按状态筛选' })
  // 对错要读详情后才知道
  const wrong = await within(statusFilter).findByRole('button', { name: /做错\s*1/ })
  expect(within(statusFilter).getByRole('button', { name: /未做\s*3/ })).toBeInTheDocument()
  // 数量为 0 的类别不显示
  expect(within(statusFilter).queryByRole('button', { name: /做对/ })).not.toBeInTheDocument()
  await userEvent.click(wrong)
  expect(router.state.location.search).toContain('status=wrong')
  const list = screen.getByRole('complementary', { name: '考点分组' })
  // 当前选中的题保留，另外只剩做错的那道
  expect(within(list).getByRole('link', { name: /参数估计/ })).toBeInTheDocument()
  expect(within(list).queryByRole('link', { name: /第 2 道/ })).not.toBeInTheDocument()
})

it('shows the source filter and tag only when a second source exists', async () => {
  renderAt('/practice')
  const sourceFilter = await screen.findByRole('group', { name: '按来源筛选' })
  expect(within(sourceFilter).getByRole('button', { name: '画像选题' })).toBeInTheDocument()
  expect(within(sourceFilter).getByRole('button', { name: '原卷补强' })).toBeInTheDocument()
  const list = screen.getByRole('complementary', { name: '考点分组' })
  expect(within(list).getByText('画像选题')).toBeInTheDocument()
})

it('offers to skip to the next unfinished practice', async () => {
  renderAt('/practice')
  const skip = await screen.findByRole('link', { name: /先跳过，做下一道/ })
  expect(skip).toHaveAttribute('href', expect.stringContaining('item=p-b'))
  // 窄窗口的切换条：点开列表
  const toggle = screen.getByRole('button', { name: /切换题目/ })
  await userEvent.click(toggle)
  expect(screen.getByRole('button', { name: /收起列表/ })).toHaveAttribute('aria-expanded', 'true')
})

it('keeps graded feedback short: conclusion first, details folded, no placeholders', async () => {
  renderAt('/practice?item=p-graded')
  const card = await screen.findByRole('region', { name: '已批改的练习' })
  // 标题只出现一次出处，章节当副标题；导航文字不当题干显示
  expect(within(card).getByRole('heading', { level: 2 })).toHaveTextContent(
    /2018 数学一 · 第 15 题\s*参数估计/,
  )
  expect(within(card).queryByText('2018 数学一 第15题 · 参数估计')).not.toBeInTheDocument()
  expect(within(card).queryByText('参考解析见原图')).not.toBeInTheDocument()
  expect(within(card).getByText('思路对了，最后一步算错了系数')).toBeVisible()
  expect(within(card).getByRole('region', { name: '问题与首错' })).toBeInTheDocument()
  for (const title of ['完整结论', '做对的部分', '参考解析']) {
    const summary = within(card).getByText(title)
    expect(summary.closest('details')).not.toHaveAttribute('open')
  }
  expect(within(card).getByRole('link', { name: /做下一道/ })).toBeInTheDocument()
})

it('tells the student when the list cannot be read', async () => {
  mockServer({
    routes: (url) =>
      url === '/api/practices' ? Promise.reject(new TypeError('Failed to fetch')) : undefined,
  })
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/practice'] })} />
    </QueryClientProvider>,
  )
  expect(await screen.findByText('练习列表没有读出来', {}, { timeout: 4000 })).toBeInTheDocument()
  expect(document.body.textContent).not.toMatch(/Failed to fetch/)
  expect(screen.getByRole('button', { name: /重试/ })).toBeInTheDocument()
})
