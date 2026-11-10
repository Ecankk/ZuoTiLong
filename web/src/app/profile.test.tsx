import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { Overview } from '../api/types'
import {
  atomsFor,
  batchBase,
  batchReady,
  emptyOverview,
  insufficientOverview,
  overview,
  trends,
} from '../mocks/profile'
import { json, mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

function renderAt(path: string) {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />
    </QueryClientProvider>,
  )
}

/** 画像接口 mock；batch 的 GET 依次返回 batchReplies */
function profileServer(data: Overview, batchReplies = [batchReady]) {
  const posts: Record<string, unknown>[] = []
  const replies = [...batchReplies]
  const fetch = mockServer({
    routes: (path, init) => {
      if (path === '/api/profile/overview') return json(data)
      if (path === '/api/profile/trends') return json(trends)
      const atoms = path.match(/^\/api\/profile\/nodes\/([^/]+)\/atoms$/)
      if (atoms) return json(atomsFor(decodeURIComponent(atoms[1])))
      if (path === '/api/practices/profile-batch' && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)))
        return json(
          {
            batch_id: 'profile-batch-1',
            source: 'profile_practice',
            requested_size: 5,
            status: 'queued',
            job_id: 'job-profile-1',
            reused: false,
          },
          202,
        )
      }
      if (path === '/api/practices/profile-batches/profile-batch-1')
        return json(replies.length > 1 ? replies.shift() : replies[0])
      return undefined
    },
  })
  return { fetch, posts }
}

const called = (fetch: ReturnType<typeof mockServer>, part: string) =>
  fetch.mock.calls.some(([url]) => String(url).includes(part))

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('leads the profile with the biggest weak spots and their checkable evidence', async () => {
  const { fetch } = profileServer(overview)
  renderAt('/profile')
  const weak = await screen.findByRole('region', { name: '最该补的地方' })
  const items = within(weak)
    .getAllByRole('listitem')
    .filter((li) => li.querySelector('strong'))
  expect(items[0]).toHaveTextContent('随机变量的数字特征')
  expect(items[0]).toHaveTextContent('近 28 天做了 6 道，错 4 道 · 3 个考点要补')
  expect(items[0]).toHaveTextContent('例：《2021数学一》第9题')
  const evidence = within(weak).getByRole('list', { name: '随机变量的数字特征的错题' })
  expect(within(evidence).getByRole('link', { name: /《2021数学一》第9题/ })).toHaveAttribute(
    'href',
    '/papers/paper-2021/questions/9',
  )
  expect(within(evidence).getByRole('link', { name: /方差及其计算式/ })).toHaveAttribute(
    'href',
    '/practice?item=probe-var-2',
  )
  expect(within(evidence).getAllByText('首错：计算')).toHaveLength(2)
  // 没有依据时如实不写，不编造
  expect(within(weak).getByText('重积分').closest('li')).not.toHaveTextContent('例：')
  // 和排行第一项相同的“最需要补”卡不重复出现
  expect(screen.queryByRole('region', { name: '哪一章最需要补' })).not.toBeInTheDocument()
  expect(screen.getByRole('region', { name: '哪一章相对稳' })).toHaveTextContent('行列式')
  expect(document.body.textContent).not.toMatch(/有效判断/)
  expect(screen.getByText('无记录：做过相关题后才会有判断')).toBeInTheDocument()
  // 趋势和热力格都是展开后才请求
  expect(called(fetch, '/api/profile/trends')).toBe(false)
  expect(called(fetch, '/atoms')).toBe(false)
  expect(document.body.textContent).not.toMatch(/undefined|null|NaN/)
})

it('loads the heatmap only when a chapter opens and trends only when expanded', async () => {
  const { fetch } = profileServer(overview)
  renderAt('/profile')
  const tree = await screen.findByRole('region', { name: '科目和章节' })
  // 默认展开排名第一的薄弱处所在科目（概率）；先展开线性代数
  await userEvent.click(within(tree).getByRole('button', { name: /^线性代数/ }))
  await userEvent.click(within(tree).getByRole('button', { name: /特征值与特征向量/ }))
  const cells = await within(tree).findByRole('list', { name: '特征值与特征向量的考点' })
  expect(within(cells).getAllByRole('listitem').length).toBe(26)
  expect(called(fetch, '/api/profile/nodes/la-eigen/atoms')).toBe(true)
  await userEvent.click(screen.getByRole('button', { name: /每周作答趋势/ }))
  expect(await screen.findByRole('img', { name: /每周作答/ })).toBeInTheDocument()
  expect(called(fetch, '/api/profile/trends?weeks=12')).toBe(true)
})

it('shows short empty states when evidence is not enough to conclude', async () => {
  profileServer(insufficientOverview)
  renderAt('/profile')
  expect(await screen.findByText('还看不出明显的薄弱处')).toBeInTheDocument()
  const conclusions = screen.getByRole('region', { name: '结论' })
  expect(conclusions).toHaveTextContent('暂时不下')
  expect(conclusions).toHaveTextContent('至少 5 道')
  expect(conclusions).toHaveTextContent('没有可比较')
})

it('explains a brand-new workspace without inventing weak spots', async () => {
  profileServer(emptyOverview)
  renderAt('/profile')
  expect(await screen.findByText('还没有作答记录')).toBeInTheDocument()
  expect(screen.getByText(/还没有选备考类别/)).toBeInTheDocument()
})

it('uses this week stats and next steps on the home page', async () => {
  profileServer(overview)
  renderAt('/')
  const week = await screen.findByRole('region', { name: '本周' })
  expect(within(week).getByText('23')).toBeInTheDocument()
  expect(within(week).getByText('11')).toBeInTheDocument()
  expect(within(week).getByText('2')).toBeInTheDocument()
  const main = screen.getByRole('region', { name: '现在做什么' })
  expect(within(main).getByRole('link', { name: /继续做/ })).toHaveAttribute(
    'href',
    '/practice?item=probe-var-3',
  )
  expect(screen.getByRole('region', { name: '最该补的地方' })).toHaveTextContent(
    '随机变量的数字特征',
  )
})

it('confirms before queuing a profile batch, shows progress and jumps to the practices', async () => {
  const { posts } = profileServer(insufficientOverview, [batchBase, batchReady])
  renderAt('/')
  const main = await screen.findByRole('region', { name: '现在做什么' })
  expect(within(main).getByRole('heading', { name: '按画像来一组' })).toBeInTheDocument()
  await userEvent.click(within(main).getByRole('radio', { name: '5 道' }))
  await userEvent.click(within(main).getByRole('button', { name: /按画像来一组/ }))
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('排一个 AI 任务')
  await userEvent.click(within(dialog).getByRole('button', { name: '开始挑题' }))
  expect(posts[0]).toMatchObject({ confirmed: true, size: 5 })
  expect(String(posts[0].request_id)).toMatch(/^[0-9a-f-]{36}$/)
  expect(await screen.findByText(/做题龙正在按画像挑题/)).toBeInTheDocument()
  expect(await screen.findByRole('link', { name: /开始做/ }, { timeout: 6000 })).toHaveAttribute(
    'href',
    '/practice?source=profile&view=topic&item=profile-probe-1',
  )
}, 10000)

it('explains why a profile batch cannot be created', async () => {
  profileServer(emptyOverview)
  renderAt('/')
  const main = await screen.findByRole('region', { name: '现在做什么' })
  expect(within(main).getByText(/先在设置里选择备考类别/)).toBeInTheDocument()
  expect(within(main).getByRole('button', { name: /按画像来一组/ })).toBeDisabled()
})
