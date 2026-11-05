import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { FreeAttempt, FreePractice } from '../api/types'
import { json, mockServer } from '../test/server'
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

const practice = (change: Partial<FreePractice> = {}): FreePractice => ({
  bank_id: 'q1',
  question_type: '选择题',
  collection_id: 'zhenti',
  question: { question_text: '下列正确的是（ ）\n\nA. $1$\n\nB. $2$\n\nC. $3$\n\nD. $4$' },
  source: { math_type: 1, year: '2025', number: 3, question_type: '选择题', max_score: 5 },
  reference: null,
  actions: ['submit', 'reveal_analysis'],
  latest_attempt: null,
  attempt_count: 0,
  ...change,
})

const attempt = (change: Partial<FreeAttempt> = {}): FreeAttempt => ({
  id: 'free-1',
  bank_id: 'q1',
  source: 'free_practice',
  question_type: '选择题',
  collection_id: 'zhenti',
  response: 'B',
  choice: 'B',
  image_ids: [],
  image_roles: {},
  answer_exposed: false,
  elapsed_seconds: 30,
  created_at: new Date().toISOString(),
  assessment: {
    correct: true,
    answer_status: 'correct',
    feedback: '回答正确',
    reference_reasoning: 'B',
  },
  job: null,
  materials: {
    question: { question_text: '下列正确的是（ ）' },
    reference: { answer_text: 'B', analysis_text: '因为 $2$ 是对的。' },
  },
  ...change,
})

/** 一个有状态的做题后端：提交成功后 GET practice 返回最近一次作答 */
function practiceServer(options: {
  view?: FreePractice
  reply?: (body: Record<string, unknown>, call: number) => Response
}) {
  let view = options.view ?? practice()
  const posts: Record<string, unknown>[] = []
  const fetch = mockServer({
    routes: (path, init) => {
      if (path === '/api/bank/q1/practice') return json(view)
      if (path === '/api/bank/q1/practice/attempts' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>
        posts.push(body)
        const response = options.reply?.(body, posts.length)
        if (response) return response
        view = { ...view, latest_attempt: attempt(), attempt_count: view.attempt_count + 1 }
        return json(attempt())
      }
      if (path === '/api/bank/q1/practice/attempts')
        return json({
          items: view.latest_attempt ? [view.latest_attempt] : [],
          total: view.attempt_count,
          offset: 0,
          limit: 10,
        })
      return undefined
    },
  })
  return { fetch, posts, setView: (next: FreePractice) => (view = next) }
}

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('judges a choice question right away and shows the reference', async () => {
  const { posts } = practiceServer({})
  renderAt('/bank/q1/practice')
  const options = await screen.findByRole('radiogroup', { name: '选项' })
  expect(
    within(options)
      .getAllByRole('radio')
      .map((r) => r.textContent),
  ).toEqual(['A', 'B', 'C', 'D'])
  await userEvent.click(within(options).getByRole('radio', { name: 'B' }))
  await userEvent.click(screen.getByRole('button', { name: '提交' }))
  const latest = await screen.findByRole('region', { name: '最近一次作答' })
  expect(await within(latest).findByText('回答正确')).toBeInTheDocument()
  expect(within(latest).getByText('参考答案与解析')).toBeInTheDocument()
  expect(posts[0]).toMatchObject({ choice: 'B', response: 'B', answer_exposed: false })
  expect(String(posts[0].request_id)).toMatch(/^[0-9a-f-]{36}$/)
  expect(typeof posts[0].elapsed_seconds).toBe('number')
})

it('shows grading in progress when a blank answer goes to AI', async () => {
  const pendingAttempt = attempt({
    question_type: '填空题',
    response: '1/2',
    choice: null,
    assessment: null,
    job: { id: 'job-free', status: 'queued' },
    materials: { question: {}, reference: null },
  })
  const { setView } = practiceServer({
    view: practice({ question_type: '填空题', question: { question_text: '求极限 ____' } }),
    reply: () => {
      setView(
        practice({ question_type: '填空题', latest_attempt: pendingAttempt, attempt_count: 1 }),
      )
      return json(pendingAttempt)
    },
  })
  renderAt('/bank/q1/practice')
  await userEvent.type(await screen.findByRole('textbox', { name: '填空答案' }), '1/2')
  await userEvent.click(screen.getByRole('button', { name: '提交' }))
  const latest = await screen.findByRole('region', { name: '最近一次作答' })
  expect(await within(latest).findByText(/正在批改/)).toBeInTheDocument()
})

it('marks the attempt as assisted after revealing the answer', async () => {
  const { fetch, posts } = practiceServer({
    view: practice({ reference: { answer_text: 'B', analysis_text: '解析内容' } }),
  })
  renderAt('/bank/q1/practice')
  await userEvent.click(await screen.findByRole('button', { name: /看答案\/解析/ }))
  const dialog = await screen.findByRole('dialog')
  await userEvent.click(within(dialog).getByRole('button', { name: '确认查看' }))
  expect(await screen.findByText(/这次作答算“受提示完成”/)).toBeInTheDocument()
  const reveal = fetch.mock.calls.find(([url]) => String(url).includes('/reveal'))
  expect(JSON.parse(String(reveal?.[1]?.body))).toEqual({ role: 'analysis', confirmed: true })
  await userEvent.click(screen.getByRole('radio', { name: 'C' }))
  await userEvent.click(screen.getByRole('button', { name: '提交' }))
  await vi.waitFor(() => expect(posts[0]).toMatchObject({ answer_exposed: true }))
})

it('reuses the request id when retrying a failed submission', async () => {
  const { posts } = practiceServer({
    reply: (_, call) => (call === 1 ? json({ error: '保存失败' }, 500) : undefined!),
  })
  renderAt('/bank/q1/practice')
  await userEvent.click(await screen.findByRole('radio', { name: 'B' }))
  await userEvent.click(screen.getByRole('button', { name: '提交' }))
  await userEvent.click(await screen.findByRole('button', { name: '重新提交' }))
  await vi.waitFor(() => expect(posts).toHaveLength(2))
  expect(posts[1]).toEqual(posts[0])
})

it('explains why a reserved question cannot be practised', async () => {
  mockServer({
    routes: (path) =>
      path === '/api/bank/q1/practice'
        ? json({ error: '题目未允许查看或属于预留卷' }, 403)
        : undefined,
  })
  renderAt('/bank/q1/practice')
  expect(await screen.findByText('这道题现在不能单独练习')).toBeInTheDocument()
  expect(screen.getByText(/留作整卷自测/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '提交' })).not.toBeInTheDocument()
})

it('searches question text within the current collection and category, and clears back', async () => {
  const fetch = mockServer()
  const router = renderAt('/bank?math_type=1')
  const input = await screen.findByRole('searchbox', { name: '搜索考点或题面' })
  await userEvent.type(input, 'f(x){enter}')
  expect(router.state.location.search).toContain('q=f')
  await vi.waitFor(() =>
    expect(
      fetch.mock.calls.some(([url]) => {
        const u = String(url)
        return u.includes('q=f') && u.includes('collection=zhenti') && u.includes('math_type=1')
      }),
    ).toBe(true),
  )
  expect(await screen.findByText('2026 数学一 · 第 7 题')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '清除题面搜索' }))
  expect(router.state.location.search).not.toContain('q=')
  expect(router.state.location.search).toContain('math_type=1')
})

it('saves the free practice switch in settings', async () => {
  const fetch = mockServer()
  renderAt('/settings')
  const card = await screen.findByRole('region', { name: '自由练习' })
  const box = within(card).getByRole('checkbox', { name: '画像计入自由练习' })
  expect(box).toBeChecked()
  await userEvent.click(box)
  const post = fetch.mock.calls.find(
    ([url, init]) => String(url) === '/api/preferences' && init?.method === 'POST',
  )
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({ include_free_practice: false })
})
