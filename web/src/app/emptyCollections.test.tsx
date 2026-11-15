import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { BankCollection } from '../api/types'
import { bankCollections, json, mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

/** 发行库：四个有题的题集 + 默认的空题集“其他”“示例” */
const released: BankCollection[] = [
  ...bankCollections.filter((c) => c.total > 0),
  { id: 'zhangyu-1000-basic', name: '张宇1000题基础篇', kind: 'book', total: 536, ready: 481 },
  { id: 'other', name: '其他', kind: 'other', total: 0, ready: 0 },
  { id: 'example', name: '示例', kind: 'example', total: 0, ready: 0 },
]

function renderAt(path: string) {
  mockServer({
    routes: (p) => (p === '/api/bank/collections' ? json(released) : undefined),
  })
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

it('never lists collections without questions on the bank page', async () => {
  renderAt('/bank')
  const tabs = await screen.findByRole('radiogroup', { name: '题集' })
  const names = within(tabs)
    .getAllByRole('radio')
    .map((r) => r.textContent)
  expect(names).toEqual(['真题', '张宇1000题', '张宇1000题基础篇'])
  expect(document.body.textContent).not.toMatch(/其他|示例/)
})

it('falls back to 真题 even when the address names an empty collection', async () => {
  renderAt('/bank?collection=other')
  const tabs = await screen.findByRole('radiogroup', { name: '题集' })
  expect(within(tabs).getByRole('radio', { name: '真题' })).toBeChecked()
  expect(within(tabs).queryByRole('radio', { name: '其他' })).not.toBeInTheDocument()
})
