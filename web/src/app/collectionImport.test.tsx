import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { BankCard, CollectionPackReport } from '../api/types'
import { bankCards, json, mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

function renderAt(path: string) {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />
    </QueryClientProvider>,
  )
}

const report = (change: Partial<CollectionPackReport> = {}): CollectionPackReport => ({
  package_sha256: 'a'.repeat(64),
  plan_sha256: 'b'.repeat(64),
  package_version: 'c0ffee1234567890',
  created_at: '2026-11-06T08:30:00Z',
  sources: [{ source_id: 'S03', revision: 'r1' }],
  trust_notice: '确认表示接受该题集及所附目录、共享索引来源；散列只能校验一致性。',
  collection: { id: 'zhangyu-1000', name: '张宇1000题', kind: 'book' },
  counts: { total: 683, ready: 632, needs_review: 49, needs_catalog: 2, unannotated: 0 },
  added: ['b1', 'b2'],
  updated: ['b3'],
  unchanged: ['b4', 'b5', 'b6'],
  catalog: { status: 'upgrade' },
  collection_conflicts: [],
  applied: false,
  ...change,
})

const zip = new File(['PK'], 'zhangyu-1000.zip', { type: 'application/zip' })

async function choosePack() {
  const card = await screen.findByRole('region', { name: '导入题集' })
  await userEvent.upload(within(card).getByLabelText('选择题集包'), zip)
  return card
}

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('previews a pack in plain words', async () => {
  const fetch = mockServer({
    routes: (path) =>
      path === '/api/library/collection-packs/preview' ? json(report()) : undefined,
  })
  renderAt('/settings')
  const card = await choosePack()
  expect(await within(card).findByText('张宇1000题（教辅）')).toBeInTheDocument()
  expect(within(card).getByText('c0ffee12')).toBeInTheDocument()
  expect(within(card).getByText(/共 683 题：可用 632 · 待核 49 · 缺考点 2/)).toBeInTheDocument()
  expect(within(card).getByText(/新增 2 题 · 更新 1 题 · 未变\s*3 题/)).toBeInTheDocument()
  expect(within(card).getByText(/会升级考点目录/)).toBeInTheDocument()
  expect(within(card).getByText(/导入即表示你信任这个题集包的来源/)).toBeInTheDocument()
  expect(card.textContent).not.toMatch(/sha256|plan|bank_id|release/i)
  const upload = fetch.mock.calls.find(([url]) => String(url).includes('/preview'))
  expect((upload?.[1]?.body as FormData).get('file')).toBeInstanceOf(File)
})

it('imports once, blocks repeated clicks during the long request and shows the backup', async () => {
  let finish: (response: Response) => void = () => undefined
  const confirms: unknown[] = []
  mockServer({
    routes: (path, init) => {
      if (path === '/api/library/collection-packs/preview') return json(report())
      if (path === '/api/library/collection-packs/confirm') {
        confirms.push(JSON.parse(String(init?.body)))
        return new Promise<Response>((resolve) => (finish = resolve))
      }
      return undefined
    },
  })
  renderAt('/settings')
  const card = await choosePack()
  const button = await within(card).findByRole('button', { name: '导入这个题集' })
  expect(button).toBeDisabled()
  await userEvent.click(within(card).getByRole('checkbox', { name: /信任这个题集包的来源/ }))
  await userEvent.click(button)
  const pending = await within(card).findByRole('button', { name: '正在导入…' })
  expect(pending).toBeDisabled()
  expect(within(card).getByText(/题多时需要几分钟/)).toBeInTheDocument()
  await userEvent.click(pending)
  expect(confirms).toEqual([
    { package_sha256: 'a'.repeat(64), plan_sha256: 'b'.repeat(64), confirmed: true },
  ])
  finish(json(report({ applied: true, backup: { path: 'D:\\备份\\library-1.zip', files: 3 } })))
  expect(await within(card).findByText(/已导入“张宇1000题”：新增 2 题/)).toBeInTheDocument()
  expect(within(card).getByText(/备份在 D:\\备份\\library-1\.zip/)).toBeInTheDocument()
})

it.each([
  [404, '暂存题集包不存在，请重新上传预演', /已失效，请重新选择文件预演/, true],
  [409, '预演已过期，请重新预演', /预演已过期：题库在这期间有变化/, true],
  [409, '正在维护题库', /正在维护题库或有任务在进行，请稍后再试/, false],
  [400, '题集文件SHA256不匹配：records.jsonl', /这个题集包不能使用/, false],
])('explains a %i error on import', async (status, error, message, again) => {
  mockServer({
    routes: (path) =>
      path === '/api/library/collection-packs/preview'
        ? json(report())
        : path === '/api/library/collection-packs/confirm'
          ? json({ error }, status)
          : undefined,
  })
  renderAt('/settings')
  const card = await choosePack()
  await userEvent.click(await within(card).findByRole('checkbox', { name: /信任/ }))
  await userEvent.click(within(card).getByRole('button', { name: '导入这个题集' }))
  expect(await within(card).findByText(message)).toBeInTheDocument()
  expect(Boolean(within(card).queryByRole('button', { name: '重新预演' }))).toBe(again)
})

it('explains an oversized pack and refuses conflicts', async () => {
  mockServer({
    routes: (path) =>
      path === '/api/library/collection-packs/preview'
        ? json({ error: '题集包超过1GiB' }, 413)
        : undefined,
  })
  renderAt('/settings')
  const card = await choosePack()
  expect(await within(card).findByText(/题集包太大/)).toBeInTheDocument()
  vi.unstubAllGlobals()

  mockServer({
    routes: (path) =>
      path === '/api/library/collection-packs/preview'
        ? json(
            report({
              catalog: { status: 'conflict' },
              collection_conflicts: [
                { bank_id: 'b1', existing: 'zhenti', requested: 'zhangyu-1000' },
              ],
            }),
          )
        : undefined,
  })
  await userEvent.upload(within(card).getByLabelText('选择题集包'), zip)
  expect(await within(card).findByText(/1 道题在本机已经属于其他题集/)).toBeInTheDocument()
  expect(within(card).getByText(/考点目录有冲突，不能导入/)).toBeInTheDocument()
  expect(within(card).queryByRole('button', { name: '导入这个题集' })).not.toBeInTheDocument()
})

it('marks corrected questions and keeps answer evidence hidden until the analysis is revealed', async () => {
  const card: BankCard = {
    ...bankCards.find((c) => c.id === 'src-2026-7')!,
    analysis_allowed: false,
    errata: [
      { role: 'stem', reason: '题干漏了条件 $x>0$', evidence: '原卷影印第 3 页' },
      { role: 'answer', reason: '答案应为 2', evidence: "$f'(1)=2$，原答案 1 有误" },
    ],
  }
  const fetch = mockServer({
    routes: (path) =>
      path === '/api/bank'
        ? json({ items: [card], total: 1, offset: 0, limit: 24, next_offset: null })
        : undefined,
  })
  renderAt('/bank?open=src-2026-7')
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getAllByText('本题已按勘误修正').length).toBeGreaterThan(0)
  expect(within(dialog).getByText(/题干漏了条件/)).toBeInTheDocument()
  expect(within(dialog).getByText(/有一处答案勘误，内容可能涉及答案/)).toBeInTheDocument()
  expect(dialog.textContent).not.toMatch(/答案应为 2|原答案 1 有误/)

  await userEvent.click(within(dialog).getByRole('button', { name: '查看解析' }))
  await userEvent.click(await screen.findByRole('button', { name: '确认查看解析' }))
  expect(await within(dialog).findByText(/答案应为 2/)).toBeInTheDocument()
  const reveal = fetch.mock.calls.find(([url]) => String(url).includes('/reveal'))
  expect(JSON.parse(String(reveal?.[1]?.body))).toEqual({ role: 'analysis', confirmed: true })
})
