import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { PageImage } from '../api/types'
import { questionDetails } from '../mocks/data'
import { pageY, segmentsFrom } from '../pages/paper/RegionEditor'
import { json, mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

// 一页 A4（842 高）按 2 倍渲染成 1684 像素高
const page = (n: number): PageImage => ({
  page: n,
  image_url: `/api/papers/paper-2023-1/pages/${n}`,
  image_width: 1190,
  image_height: 1684,
  scale: 2,
})

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('converts page clicks and existing regions', () => {
  // 显示高度 421（缩小 4 倍），点在 100 处：100 * 1684 / 421 / 2 = 200
  expect(pageY(page(1), 100, 421)).toBe(200)
  expect(
    segmentsFrom([
      { page: 5, bbox: [0, 300, 595, 500], role: 'q' },
      { page: 4, bbox: [0, 600, 595, 800], role: 'q' },
      { page: 4, bbox: [0, 100, 595, 200], role: 'q' },
    ]),
  ).toEqual([
    { page: 4, top: 100, bottom: 800 },
    { page: 5, top: 300, bottom: 500 },
  ])
})

it('adjusts the crop by dragging, explains a busy paper and retries with the same request', async () => {
  const posts: Record<string, unknown>[] = []
  const detail = questionDetails[0]
  const fetch = mockServer({
    routes: (path, init) => {
      if (path === '/api/papers/paper-2023-1/pages') return json({ items: [page(4), page(5)] })
      if (path === `/api/papers/paper-2023-1/questions/${detail.question.id}/regions`) {
        posts.push(JSON.parse(String(init?.body)))
        return posts.length === 1
          ? json({ error: '试卷有任务正在运行' }, 409)
          : json({ question_id: detail.question.id, status: 'adjusted' })
      }
      return undefined
    },
  })
  // 整页图显示为 421 像素高
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    top: 0,
    height: 421,
    left: 0,
    width: 300,
    bottom: 421,
    right: 300,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider
        router={createMemoryRouter(routes, {
          initialEntries: [`/papers/paper-2023-1/questions/${detail.question.number}`],
        })}
      />
    </QueryClientProvider>,
  )
  await userEvent.click(await screen.findByRole('button', { name: '调整切图' }))
  const dialog = await screen.findByRole('dialog', { name: /调整第 \d+ 题的原卷图/ })
  const image = await within(dialog).findByRole('img', { name: '原卷第 4 页' })
  // 原来是 120–420；点在显示高度 20 处（= 40）把上线移上去
  fireEvent.pointerDown(image.parentElement!, { clientY: 20, pointerId: 1 })
  fireEvent.pointerUp(image.parentElement!)
  expect(within(dialog).getByText('约占整页的 45%')).toBeInTheDocument()

  await userEvent.click(within(dialog).getByRole('button', { name: /加一段/ }))
  expect(within(dialog).getByRole('region', { name: '第 2 段' })).toBeInTheDocument()
  await userEvent.click(
    within(within(dialog).getByRole('region', { name: '第 2 段' })).getByRole('button', {
      name: /去掉这段/,
    }),
  )

  await userEvent.click(within(dialog).getByRole('button', { name: '下一步' }))
  expect(within(dialog).getByText('只改这道题显示的原卷图，不改判断结果。')).toBeInTheDocument()
  await userEvent.click(within(dialog).getByRole('button', { name: '确认调整' }))
  expect(await within(dialog).findByText(/有任务正在进行或已经归档/)).toBeInTheDocument()
  await userEvent.click(within(dialog).getByRole('button', { name: '确认调整' }))
  await vi.waitFor(() => expect(posts).toHaveLength(2))
  expect(posts[0]).toMatchObject({
    confirmed: true,
    regions: [{ page: 4, top: 40, bottom: 420 }],
  })
  expect(String(posts[0].request_id)).toMatch(/^[0-9a-f-]{36}$/)
  expect(posts[1]).toEqual(posts[0])
  await vi.waitFor(() =>
    expect(screen.queryByRole('dialog', { name: /调整第/ })).not.toBeInTheDocument(),
  )
  expect(fetch).toHaveBeenCalled()
})
