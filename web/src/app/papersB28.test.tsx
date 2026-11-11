import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { todayDay } from '../lib/examDate'
import { clearImport, datedList, duplicateDetail, duplicateImport } from '../mocks/papersB28'
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

const pdf = (name: string) => new File(['%PDF'], name, { type: 'application/pdf' })

type Server = {
  imports: FormData[]
  dates: Record<string, unknown>[]
  decisions: Record<string, unknown>[]
  detailReads: number
}

function server({
  importReply = (n: number) => clearImport(`new-${n}`),
  decisionStatus = 200,
  decisionReason = 'has_history',
  detail = () => duplicateDetail as unknown,
}: {
  importReply?: (n: number) => unknown
  decisionStatus?: number | ((call: number) => number)
  decisionReason?: string
  detail?: (reads: number) => unknown
} = {}) {
  const state: Server = { imports: [], dates: [], decisions: [], detailReads: 0 }
  mockServer({
    routes: (path, init) => {
      if (path === '/api/papers') return json(datedList)
      if (path === '/api/papers/import' && init?.method === 'POST') {
        state.imports.push(init.body as FormData)
        return json(importReply(state.imports.length), 201)
      }
      if (path === '/api/papers/dates' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        state.dates.push(body)
        return json({
          updated: body.paper_ids.map((id: string) => ({ paper_id: id, ...body })),
          reused: false,
        })
      }
      if (path === '/api/papers/p-dup/import-decision' && init?.method === 'POST') {
        state.decisions.push(JSON.parse(String(init.body)))
        const status =
          typeof decisionStatus === 'function'
            ? decisionStatus(state.decisions.length)
            : decisionStatus
        return status === 200
          ? json({ paper_id: 'p-dup', import_decision: 'accepted', reused: false })
          : json({ error: '上传状态已变化，请刷新后重试', reason: decisionReason }, status)
      }
      if (path === '/api/papers/p-dup') {
        state.detailReads += 1
        return json(detail(state.detailReads))
      }
      return undefined
    },
  })
  return state
}

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('shows each exam date at its precision and keeps unknown dates after known ones', async () => {
  server()
  renderAt('/papers')
  const cards = await screen.findAllByRole('article')
  expect(cards.map((card) => card.querySelector('h3')?.textContent)).toEqual([
    '《2023 数学一（重做）》',
    '《2023 数学一》',
    '《2022 数学一》',
    '《2019 数学一》',
    '《2020 数学一》',
  ])
  expect(cards[0]).toHaveTextContent('约2026年11月作答')
  expect(cards[0]).toHaveTextContent('待确认是否重做')
  expect(cards[1]).toHaveTextContent('2026年10月18日作答')
  expect(cards[2]).toHaveTextContent('约2026年10月作答')
  expect(cards[3]).toHaveTextContent('作答日期未知')
  expect(cards[4]).toHaveTextContent('作答日期记不清')
  expect(document.body.textContent).not.toMatch(/undefined|null|NaN|精度/)
})

it('never sends a date the user did not choose; "今天" is only a button', async () => {
  const state = server()
  const router = renderAt('/papers')
  const upload = await screen.findByRole('region', { name: '上传试卷' })
  await userEvent.upload(within(upload).getByLabelText('选择试卷 PDF'), pdf('2024数一.pdf'))
  expect(within(upload).getByRole('combobox', { name: '作答日期' })).toHaveValue('none')
  await userEvent.click(within(upload).getByRole('button', { name: '上传' }))
  await vi.waitFor(() => expect(state.imports).toHaveLength(1))
  const form = state.imports[0]
  expect(form.get('title')).toBe('2024数一')
  expect(form.has('exam_date')).toBe(false)
  expect(form.has('exam_date_precision')).toBe(false)
  expect(form.has('exam_date_unknown_reason')).toBe(false)
  await vi.waitFor(() => expect(router.state.location.pathname).toBe('/papers/new-1'))
})

it('lets a batch share one date, then changes a single paper before uploading', async () => {
  const state = server()
  renderAt('/papers')
  const upload = await screen.findByRole('region', { name: '上传试卷' })
  await userEvent.upload(within(upload).getByLabelText('选择试卷 PDF'), [
    pdf('a.pdf'),
    pdf('b.pdf'),
    pdf('c.pdf'),
  ])
  await userEvent.selectOptions(
    within(upload).getByRole('combobox', { name: '统一设置作答日期' }),
    'month',
  )
  await userEvent.type(within(upload).getByLabelText('统一设置作答日期：大约哪个月'), '2026-09')
  await userEvent.click(within(upload).getByRole('button', { name: '应用到全部' }))
  // 第二份改成“记不清”，第三份改成具体日期并点“今天”
  await userEvent.selectOptions(
    within(upload).getByRole('combobox', { name: 'b.pdf 的作答日期' }),
    'forgotten',
  )
  await userEvent.selectOptions(
    within(upload).getByRole('combobox', { name: 'c.pdf 的作答日期' }),
    'day',
  )
  expect(within(upload).getByRole('button', { name: '上传 3 份' })).toBeDisabled()
  await userEvent.click(within(upload).getByRole('button', { name: '今天' }))
  await userEvent.click(within(upload).getByRole('button', { name: '上传 3 份' }))
  await vi.waitFor(() => expect(state.imports).toHaveLength(3))
  const sent = state.imports.map((form) => [
    form.get('exam_date'),
    form.get('exam_date_precision'),
    form.get('exam_date_unknown_reason'),
  ])
  expect(sent).toEqual([
    ['2026-09', 'month', null],
    [null, 'unknown', 'forgotten'],
    [todayDay(), 'day', null],
  ])
  expect(await within(upload).findAllByRole('link', { name: '已上传，去核对题号' })).toHaveLength(3)
})

it('asks whether a same-exam upload is a retake and sends the decision', async () => {
  const state = server({ importReply: () => duplicateImport })
  const router = renderAt('/papers')
  const upload = await screen.findByRole('region', { name: '上传试卷' })
  await userEvent.upload(within(upload).getByLabelText('选择试卷 PDF'), pdf('2023再做.pdf'))
  await userEvent.click(within(upload).getByRole('button', { name: '上传' }))
  const dialog = await screen.findByRole('dialog', { name: '这份卷之前传过' })
  expect(dialog).toHaveTextContent('2023 年数学一')
  expect(dialog).toHaveTextContent('2026年10月18日作答 · 已分析')
  await userEvent.click(within(dialog).getByRole('button', { name: '这是重做' }))
  await vi.waitFor(() => expect(state.decisions).toHaveLength(1))
  expect(state.decisions[0]).toMatchObject({
    confirmed: true,
    decision: 'retake',
    decision_revision: 'rev-1',
  })
  expect(String(state.decisions[0].request_id)).toMatch(/^[0-9a-f-]{36}$/)
  await vi.waitFor(() => expect(router.state.location.pathname).toBe('/papers/p-dup'))
})

it('can postpone the decision; the paper detail hides analysis and re-reads on a conflict', async () => {
  const state = server({ decisionStatus: 409 })
  renderAt('/papers/p-dup')
  const notice = await screen.findByRole('region', { name: '这份卷之前传过' })
  expect(screen.queryByRole('button', { name: /开始分析/ })).not.toBeInTheDocument()
  await userEvent.click(within(notice).getByRole('button', { name: '去决定' }))
  let dialog = await screen.findByRole('dialog')
  await userEvent.click(within(dialog).getByRole('button', { name: '稍后再决定' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await userEvent.click(within(notice).getByRole('button', { name: '去决定' }))
  dialog = await screen.findByRole('dialog')
  const reads = state.detailReads
  await userEvent.click(within(dialog).getByRole('button', { name: '传错了，撤回' }))
  expect(await within(dialog).findByText(/不能撤回了/)).toBeInTheDocument()
  await vi.waitFor(() => expect(state.detailReads).toBeGreaterThan(reads))
})

it('changes the exam date of several papers at once', async () => {
  const state = server()
  renderAt('/papers')
  await screen.findAllByRole('article')
  await userEvent.click(screen.getByRole('button', { name: '修改作答日期' }))
  await userEvent.click(screen.getByRole('checkbox', { name: '选择 《2019 数学一》' }))
  await userEvent.click(screen.getByRole('checkbox', { name: '选择 《2020 数学一》' }))
  const bar = screen.getByRole('region', { name: '选择要改日期的试卷' })
  expect(bar).toHaveTextContent('已选 2 份')
  await userEvent.click(within(bar).getByRole('button', { name: '设置日期' }))
  const dialog = await screen.findByRole('dialog', { name: '修改 2 份试卷的作答日期' })
  expect(dialog).toHaveTextContent('可能被自动填成了上传当天')
  await userEvent.selectOptions(within(dialog).getByRole('combobox'), 'month')
  await userEvent.type(within(dialog).getByLabelText(/大约哪个月/), '2025-12')
  await userEvent.click(within(dialog).getByRole('button', { name: '保存日期' }))
  await vi.waitFor(() => expect(state.dates).toHaveLength(1))
  expect(state.dates[0]).toMatchObject({
    confirmed: true,
    paper_ids: ['p-unknown', 'p-forgot'],
    exam_date: '2025-12',
    exam_date_precision: 'month',
    exam_date_unknown_reason: null,
  })
  await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

it('edits one paper date from its detail page, prefilled with the current value', async () => {
  const state = server()
  renderAt('/papers/p-dup')
  await screen.findByRole('region', { name: '这份卷之前传过' })
  expect(screen.getByText(/约2026年11月作答/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '改日期' }))
  const dialog = await screen.findByRole('dialog', { name: '修改作答日期' })
  expect(within(dialog).getByRole('combobox')).toHaveValue('month')
  expect(within(dialog).getByLabelText(/大约哪个月/)).toHaveValue('2026-11')
  await userEvent.selectOptions(within(dialog).getByRole('combobox'), 'forgotten')
  await userEvent.click(within(dialog).getByRole('button', { name: '保存日期' }))
  await vi.waitFor(() => expect(state.dates).toHaveLength(1))
  expect(state.dates[0]).toMatchObject({
    paper_ids: ['p-dup'],
    exam_date: null,
    exam_date_precision: 'unknown',
    exam_date_unknown_reason: 'forgotten',
  })
})

it('says the date was not changed when the same PDF was uploaded before', async () => {
  const state = server({
    importReply: () => ({ ...clearImport('p-day'), reused: true, date_ignored: true }),
  })
  const router = renderAt('/papers')
  const upload = await screen.findByRole('region', { name: '上传试卷' })
  await userEvent.upload(within(upload).getByLabelText('选择试卷 PDF'), pdf('2023数一.pdf'))
  await userEvent.selectOptions(
    within(upload).getByRole('combobox', { name: '作答日期' }),
    'forgotten',
  )
  await userEvent.click(within(upload).getByRole('button', { name: '上传' }))
  await vi.waitFor(() => expect(state.imports).toHaveLength(1))
  expect(await within(upload).findByText(/这个文件之前传过，日期没改/)).toBeInTheDocument()
  // 不跳走，给出到原卷改日期的入口
  expect(router.state.location.pathname).toBe('/papers')
  expect(within(upload).getByRole('link', { name: '改日期' })).toHaveAttribute(
    'href',
    '/papers/p-day?editDate=1',
  )
})

it('opens the date dialog when arriving from the upload result', async () => {
  server()
  renderAt('/papers/p-dup?editDate=1')
  expect(await screen.findByRole('dialog', { name: '修改作答日期' })).toBeInTheDocument()
})

it('notes when the exam year and type could not be recognised, without blocking', async () => {
  const unresolved = {
    status: 'unresolved' as const,
    identity: null,
    reason: null,
    matches: [],
  }
  server({ importReply: (n) => ({ ...clearImport(`new-${n}`), duplicate_check: unresolved }) })
  const router = renderAt('/papers')
  const upload = await screen.findByRole('region', { name: '上传试卷' })
  await userEvent.upload(within(upload).getByLabelText('选择试卷 PDF'), pdf('扫描件.pdf'))
  await userEvent.click(within(upload).getByRole('button', { name: '上传' }))
  expect(
    await within(upload).findByText('没能认出是哪一年哪一卷，无法检查是否重复上传'),
  ).toBeInTheDocument()
  expect(within(upload).getByRole('link', { name: '已上传，去核对题号' })).toHaveAttribute(
    'href',
    '/papers/new-1',
  )
  expect(router.state.location.pathname).toBe('/papers')
})

it('retries a decision with the fresh revision after a stale-revision conflict', async () => {
  const state = server({
    importReply: () => duplicateImport,
    decisionStatus: (call) => (call === 1 ? 409 : 200),
    decisionReason: 'revision_stale',
    detail: () => ({ ...duplicateDetail, decision_revision: 'rev-2' }),
  })
  renderAt('/papers')
  const upload = await screen.findByRole('region', { name: '上传试卷' })
  await userEvent.upload(within(upload).getByLabelText('选择试卷 PDF'), pdf('2023再做.pdf'))
  await userEvent.click(within(upload).getByRole('button', { name: '上传' }))
  const dialog = await screen.findByRole('dialog', { name: '这份卷之前传过' })
  await userEvent.click(within(dialog).getByRole('button', { name: '这是重做' }))
  expect(await within(dialog).findByText(/情况刚刚有变化，已重新读取/)).toBeInTheDocument()
  await vi.waitFor(() => expect(state.detailReads).toBeGreaterThan(0))
  await userEvent.click(within(dialog).getByRole('button', { name: '这是重做' }))
  await vi.waitFor(() => expect(state.decisions).toHaveLength(2))
  expect(state.decisions[0].decision_revision).toBe('rev-1')
  expect(state.decisions[1].decision_revision).toBe('rev-2')
})

it('explains a date change refused because a paper was withdrawn', async () => {
  mockServer({
    routes: (path, init) => {
      if (path === '/api/papers') return json(datedList)
      if (path === '/api/papers/dates' && init?.method === 'POST')
        return json({ error: '已撤回', reason: 'withdrawn' }, 409)
      return undefined
    },
  })
  renderAt('/papers')
  await screen.findAllByRole('article')
  await userEvent.click(screen.getByRole('button', { name: '修改作答日期' }))
  await userEvent.click(screen.getByRole('checkbox', { name: '选择 《2019 数学一》' }))
  await userEvent.click(screen.getByRole('button', { name: '设置日期' }))
  const dialog = await screen.findByRole('dialog')
  await userEvent.selectOptions(within(dialog).getByRole('combobox'), 'forgotten')
  await userEvent.click(within(dialog).getByRole('button', { name: '保存日期' }))
  expect(
    await within(dialog).findByText('选中的试卷里有已经撤回的，不能改日期。'),
  ).toBeInTheDocument()
})
