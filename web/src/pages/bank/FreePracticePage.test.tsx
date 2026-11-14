import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { FreePractice } from '../../api/types'
import { createQueryClient } from '../../app/queryClient'
import { routes } from '../../app/routes'
import { json, mockServer } from '../../test/server'

const view: FreePractice = {
  bank_id: 'q1',
  question_type: '解答题',
  collection_id: 'zhenti',
  question: { question_text: '求 $\\lim_{x\\to0}\\frac{\\sin x}{x}$。' },
  source: { math_type: 1, year: '2025', number: 17, question_type: '解答题', max_score: 10 },
  reference: null,
  actions: ['submit'],
  latest_attempt: null,
  attempt_count: 0,
}

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

it('lets a masked question be revealed and practised instead of a dead end', async () => {
  let revealed = false
  const fetch = mockServer({
    routes: (path, init) => {
      if (path === '/api/bank/q1/practice')
        return revealed ? json(view) : json({ error: '题目未允许查看或属于预留卷' }, 403)
      if (path === '/api/bank/q1/reveal' && init?.method === 'POST') {
        revealed = true
        return json({ ok: true })
      }
      return undefined
    },
  })
  renderAt('/bank/q1/practice')
  expect(await screen.findByText('这道题现在不能单独练习')).toBeInTheDocument()
  // 原因分不清时两条出路都说明
  expect(screen.getByText(/如果是默认遮挡的同类别真题/)).toBeInTheDocument()
  expect(screen.getByText(/如果这套卷你留作整卷自测/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '确认查看后再做' }))
  const dialog = await screen.findByRole('dialog')
  await userEvent.click(within(dialog).getByRole('button', { name: '确认查看题目' }))
  const reveal = fetch.mock.calls.find(([url]) => String(url).includes('/reveal'))
  expect(JSON.parse(String(reveal?.[1]?.body))).toEqual({ role: 'question', confirmed: true })
  expect(await screen.findByRole('region', { name: '作答' })).toBeInTheDocument()
  expect(screen.queryByText('这道题现在不能单独练习')).not.toBeInTheDocument()
})

it('shows a friendly sentence instead of an English error when the server is gone', async () => {
  mockServer({
    routes: (path) =>
      path === '/api/bank/q1/practice'
        ? Promise.reject(new TypeError('Failed to fetch'))
        : undefined,
  })
  renderAt('/bank/q1/practice')
  expect(await screen.findByText('没有打开这道题')).toBeInTheDocument()
  expect(document.body.textContent).not.toMatch(/Failed to fetch/)
  expect(screen.getByText(/连不上做题龙/)).toBeInTheDocument()
})

it('keeps the timer out of sight until asked, and remembers the choice', async () => {
  const fetch = mockServer({
    routes: (path) => (path === '/api/bank/q1/practice' ? json(view) : undefined),
  })
  renderAt('/bank/q1/practice')
  const card = await screen.findByRole('region', { name: '作答' })
  const toggle = within(card).getByRole('button', { name: /显示用时/ })
  expect(within(card).queryByLabelText('已用时间')).not.toBeInTheDocument()
  await userEvent.click(toggle)
  expect(within(card).getByLabelText('已用时间')).toHaveTextContent(/^\d{2}:\d{2}$/)
  // 记在后端草稿里（桌面版每次启动 origin 都变，浏览器存储留不住）
  await vi.waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([url, init]) =>
          String(url).includes('/api/drafts') &&
          init?.method === 'POST' &&
          JSON.parse(String(init.body)).key === 'zuotilong:free-practice-show-timer' &&
          JSON.parse(String(init.body)).value === true,
      ),
    ).toBe(true),
  )
  expect(localStorage.getItem('zuotilong:free-practice-show-timer')).toBeNull()
})
