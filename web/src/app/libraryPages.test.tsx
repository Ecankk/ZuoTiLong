import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

describe('bank page', () => {
  it('lists questions with type, score, topics and hides reserved ones with the reason', async () => {
    mockServer()
    renderAt('/bank?math_type=1')
    expect(await screen.findByText('2026 数学一 · 第 7 题')).toBeInTheDocument()
    expect(screen.getByText('5 分')).toBeInTheDocument()
    expect(screen.getByText('这套试卷留作整卷自测')).toBeInTheDocument()
    expect((await screen.findAllByRole('link', { name: '等价无穷小替换' }))[0]).toHaveAttribute(
      'href',
      '/topics/a1',
    )
  })

  it('defaults to past exams, hides empty collections and shows book questions by section', async () => {
    const fetch = mockServer()
    renderAt('/bank')
    const tabs = await screen.findByRole('radiogroup', { name: '题集' })
    expect(within(tabs).getByRole('radio', { name: '真题' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    expect(within(tabs).queryByRole('radio', { name: '其他' })).not.toBeInTheDocument()
    expect(await screen.findByText('2026 数学一 · 第 7 题')).toBeInTheDocument()
    expect(screen.getByLabelText('年份')).toBeInTheDocument()
    const types = screen.getByRole('radiogroup', { name: '数学类别' })
    expect(
      within(types)
        .getAllByRole('radio')
        .map((r) => r.textContent),
    ).toEqual(['全部', '数一'])

    await userEvent.click(within(tabs).getByRole('radio', { name: '张宇1000题' }))
    expect(await screen.findByRole('heading', { name: '第 3 题 · 计算题' })).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: '强化篇 · 第一章 函数极限', level: 2 }),
    ).toBeInTheDocument()
    expect(screen.getByText('题号未知的教辅题')).toBeInTheDocument()
    expect(screen.queryByLabelText('年份')).not.toBeInTheDocument()
    const bookTypes = screen.getByRole('radiogroup', { name: '数学类别' })
    expect(
      within(bookTypes)
        .getAllByRole('radio')
        .map((r) => r.textContent),
    ).toEqual(['全部', '数一'])
    await userEvent.click(within(bookTypes).getByRole('radio', { name: '数一' }))
    await vi.waitFor(() =>
      expect(
        fetch.mock.calls.some(
          ([url]) => /collection=zhangyu-1000/.test(String(url)) && /math_type=1/.test(String(url)),
        ),
      ).toBe(true),
    )
    expect(screen.queryByText('2026 数学一 · 第 7 题')).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/null|undefined/)
    const urls = fetch.mock.calls
      .map(([url]) => String(url))
      .filter((u) => u.startsWith('/api/bank?'))
    expect(urls.every((u) => u.includes('collection='))).toBe(true)
  })

  it('asks before showing the analysis and reveals it when not yet allowed', async () => {
    const fetch = mockServer()
    renderAt('/bank?open=src-2026-7')
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: '查看解析' }))
    const confirm = await screen.findByRole('button', { name: '确认查看解析' })
    await userEvent.click(confirm)
    const reveal = fetch.mock.calls.find(([url]) => String(url).includes('/reveal'))
    expect(String(reveal?.[0])).toContain('/api/bank/src-2026-7/reveal')
    expect(JSON.parse(String(reveal?.[1]?.body))).toEqual({ role: 'analysis', confirmed: true })
    expect(await screen.findByText('参考解析')).toBeInTheDocument()
  })
})

describe('topics page', () => {
  it('shows the tree, searches by alias and opens a topic with its stats', async () => {
    mockServer()
    renderAt('/topics/a1')
    expect(await screen.findByText('乘除因子中可用等价无穷小整体替换。')).toBeInTheDocument()
    expect(screen.getByText('需要关注')).toBeInTheDocument()
    // 按题集分开：顺序跟随题集列表（真题在前），题数来自各题集计数，不相加
    const tabs = await screen.findByRole('group', { name: '题集' })
    expect(within(tabs).getByRole('button', { name: '真题 9 题' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('link', { name: '在题库中查看真题的全部 9 题' })).toHaveAttribute(
      'href',
      '/bank?collection=zhenti&topic=a1',
    )
    await userEvent.click(within(tabs).getByRole('button', { name: '张宇1000题 5 题' }))
    expect(
      await screen.findByRole('link', { name: /^强化篇 · 第一章 函数极限 · 第 3 题/ }),
    ).toHaveAttribute('href', '/bank?collection=zhangyu-1000&topic=a1&open=zy-q-3')
    expect(document.body.textContent).not.toMatch(/12 题/)
    await userEvent.type(screen.getByPlaceholderText('搜索考点名称或别名'), '代换')
    expect(
      within(screen.getByLabelText('考点目录')).getByText('等价无穷小替换'),
    ).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/原子/)
  })

  it('follows a historical topic id to the current one', async () => {
    mockServer()
    const router = renderAt('/topics/old-id')
    expect(await screen.findByText('乘除因子中可用等价无穷小整体替换。')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/topics/a1')
  })
})
