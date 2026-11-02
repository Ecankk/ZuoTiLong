import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
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

/** 界面不出现开发概念（设计规范“术语”）。 */
const forbidden = /Agent|Codex|会话|CLI|检验题|原子考点|本轮/

describe('app shell', () => {
  it('shows navigation, background progress and the home page without developer terms', async () => {
    renderAt('/')
    expect(await screen.findByText('确认《2023 数学一》第 7 题的作答')).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: '主导航' })
    expect(
      within(nav)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['首页', '试卷', '练习5', '考点', '画像', '题库'])
    expect(await screen.findByRole('button', { name: '后台进度，点开查看全部' })).toHaveTextContent(
      '做题龙正在分析《2023 数学一》',
    )
    expect(document.body.textContent).not.toMatch(forbidden)
  })

  it('opens the first wrong question when entering the question analysis', async () => {
    const router = renderAt('/papers/paper-2023-1/questions')
    expect(await screen.findByText('这道题的逐题分析暂时无法显示。')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/papers/paper-2023-1/questions/3')
  })

  it('renders the analysed question with grouped question numbers', async () => {
    renderAt('/papers/paper-2023-1/questions/17')
    expect(await screen.findByText('应该是')).toBeInTheDocument()
    expect(screen.getByText('选择题')).toBeInTheDocument()
    expect(screen.getByText('第 2 步 · 首个错误')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(forbidden)
  })

  it('lists practice by topic and reveals a masked question on request', async () => {
    renderAt('/practice')
    const reveal = await screen.findByRole('button', { name: '查看题目' })
    expect(screen.getByText('数学一真题，默认遮挡')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '提交并批改' })).toBeDisabled()
    await userEvent.click(reveal)
    expect(await screen.findByText(/求常数/)).toBeInTheDocument()
    expect(await screen.findByText('思路对了，最后一步算错了系数')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(forbidden)
  })
})
