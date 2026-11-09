import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

/** 把响应里所有 access 换成题集题的样子：没有年份、类别和题号 */
function asCollectionQuestions(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(asCollectionQuestions)
  if (!value || typeof value !== 'object') return value
  const entries = Object.entries(value).map(([key, item]) => {
    if (key !== 'access' || !item || typeof item !== 'object')
      return [key, asCollectionQuestions(item)]
    const rest: Record<string, unknown> = { ...item, masked: false, can_view: true }
    delete rest.year
    delete rest.math_type
    delete rest.number
    return [key, rest]
  })
  return Object.fromEntries(entries)
}

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('shows collection practice questions without undefined or 第 0 题', async () => {
  const fetch = mockServer()
  const original = fetch.getMockImplementation()!
  fetch.mockImplementation(async (input, init) => {
    const response = await original(input, init)
    if (!String(input).startsWith('/api/practices') || !response.ok) return response
    return new Response(JSON.stringify(asCollectionQuestions(await response.json())), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/practice'] })} />
    </QueryClientProvider>,
  )
  expect((await screen.findAllByText(/第 1 道/)).length).toBeGreaterThan(0)
  const text = document.querySelector('main')?.textContent ?? ''
  expect(text).not.toMatch(/undefined|第 0 题|null/)
})
