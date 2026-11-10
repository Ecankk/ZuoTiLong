import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { endpoints } from '../api/endpoints'
import { mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('builds the practices query with source, batch and grouping', async () => {
  const fetch = mockServer()
  await endpoints.practices('batch', false, { source: 'profile', batchId: 'profile-batch-1' })
  const url = new URL(String(fetch.mock.calls[0][0]), 'http://localhost')
  expect(url.pathname).toBe('/api/practices')
  expect(Object.fromEntries(url.searchParams)).toMatchObject({
    group_by: 'batch',
    source: 'profile',
    batch_id: 'profile-batch-1',
    include_inactive: 'false',
  })
})

it('narrows the practice page to one profile batch when opened from a batch', async () => {
  const fetch = mockServer()
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider
        router={createMemoryRouter(routes, {
          initialEntries: ['/practice?source=profile&view=topic&batch=profile-batch-1'],
        })}
      />
    </QueryClientProvider>,
  )
  expect(await screen.findByText(/只看这一组按画像选的题/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '看全部练习' }).getAttribute('href')).not.toMatch(
    /batch=/,
  )
  const list = fetch.mock.calls
    .map(([u]) => String(u))
    .find((u) => u.startsWith('/api/practices?') && u.includes('batch_id'))
  expect(list).toContain('source=profile')
  expect(list).toContain('batch_id=profile-batch-1')
})
