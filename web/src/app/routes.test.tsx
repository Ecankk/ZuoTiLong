import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { tasks } from '../mocks/data'
import { mockServer } from '../test/server'
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

/** 普通界面不出现开发概念（设计规范“术语”）。 */
const forbidden = /Agent|Codex|会话|CLI|检验题|原子考点|本轮/
const mainText = () => document.querySelector('main')?.textContent ?? ''

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

describe('app shell', () => {
  it('shows navigation, background progress and derived home todos', async () => {
    mockServer()
    renderAt('/')
    expect(await screen.findByText('加减运算中的等价无穷小替换')).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: '主导航' })
    expect(
      within(nav)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['首页', '试卷', '练习5', '考点', '画像', '题库'])
    expect(await screen.findByRole('button', { name: '后台进度，点开查看全部' })).toHaveTextContent(
      '做题龙正在分析《2023 数学一》',
    )
    expect(mainText()).not.toMatch(forbidden)
  })

  it('lists papers with the pen convention and without guessing missing scores', async () => {
    mockServer()
    renderAt('/papers')
    expect(await screen.findByText('《2023 数学一》')).toBeInTheDocument()
    expect(screen.getByText('红笔：事后批改')).toBeInTheDocument()
    expect(screen.getByText('总分待核定')).toBeInTheDocument()
  })

  it('opens the first wrong question when entering the question analysis', async () => {
    mockServer()
    const router = renderAt('/papers/paper-2023-1/questions')
    expect(await screen.findByText('这道题的逐题分析暂时无法显示。')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/papers/paper-2023-1/questions/3')
  })

  it('renders the analysed question with grouped question numbers', async () => {
    mockServer()
    renderAt('/papers/paper-2023-1/questions/17')
    expect(await screen.findByText('应该是')).toBeInTheDocument()
    expect(screen.getByText('选择题')).toBeInTheDocument()
    expect(screen.getByText('第 2 步 · 首个错误')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '泰勒公式求极限' })).toHaveAttribute(
      'href',
      '/topics/topic-taylor-limit',
    )
    expect(mainText()).not.toMatch(forbidden)
  })

  it('asks before revealing a masked practice question', async () => {
    const fetch = mockServer()
    renderAt('/practice')
    expect(await screen.findByText('数学一真题，默认遮挡')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '查看题目' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: '确认查看题目' }))
    const reveal = fetch.mock.calls.find(([url]) => String(url).includes('/reveal'))
    expect(JSON.parse(String(reveal?.[1]?.body))).toEqual({ role: 'question', confirmed: true })
    expect(await screen.findByText('思路对了，最后一步算错了系数')).toBeInTheDocument()
    expect(mainText()).not.toMatch(forbidden)
  })

  it('saves only the changed study type', async () => {
    const fetch = mockServer()
    renderAt('/settings')
    await userEvent.click(await screen.findByRole('radio', { name: '数学二' }))
    expect(await screen.findByText('已保存')).toBeInTheDocument()
    const post = fetch.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ study_type: 2 })
  })
})

describe('onboarding', () => {
  it('opens on first visit and shows the live AI service state', async () => {
    localStorage.clear()
    mockServer({
      tasks: {
        ...tasks,
        active: null,
        availability: { status: 'unavailable', reason: 'not_installed', message: '' },
      },
    })
    renderAt('/')
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('做题龙能做什么')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: '下一步' }))
    expect(await within(dialog).findByText('未安装')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: '跳过引导' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(localStorage.getItem('zuotilong:onboarding-seen')).toBe('1')
  })
})
