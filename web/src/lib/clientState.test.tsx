import { QueryClientProvider } from '@tanstack/react-query'
import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { createQueryClient } from '../app/queryClient'
import { routes } from '../app/routes'
import { json, mockServer } from '../test/server'
import { clientStateKeys, useClientState } from './clientState'

/** /api/drafts 的内存实现：记录每次写入 */
function draftsServer(initial: Record<string, unknown> = {}) {
  const store = new Map(Object.entries(initial))
  const posts: { key: string; value: unknown }[] = []
  const fetch = mockServer({
    routes: (path, init, url) => {
      if (path !== '/api/drafts') return undefined
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        posts.push(body)
        store.set(body.key, body.value)
        return json({ ok: true })
      }
      const key = url.searchParams.get('key') ?? ''
      return json(store.has(key) ? { key, value: store.get(key) } : {})
    },
  })
  return { fetch, posts, store }
}

/** 每个测试一个 QueryClient（不能在 wrapper 里每次渲染都新建） */
function makeWrapper() {
  const client = createQueryClient()
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

const timerOptions = {
  fallback: false,
  fromLegacy: (raw: string) => (raw === '1' ? true : raw === '0' ? false : undefined),
}

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('migrates an old localStorage value once and then forgets it', async () => {
  localStorage.setItem(clientStateKeys.freePracticeTimer, '1')
  const { posts } = draftsServer()
  const { result } = renderHook(
    () => useClientState(clientStateKeys.freePracticeTimer, timerOptions),
    { wrapper: makeWrapper() },
  )
  await waitFor(() => expect(result.current.ready).toBe(true))
  expect(result.current.value).toBe(true)
  expect(posts).toEqual([{ key: clientStateKeys.freePracticeTimer, value: true }])
  expect(localStorage.getItem(clientStateKeys.freePracticeTimer)).toBeNull()
})

it('prefers the stored draft and drops a stale localStorage copy', async () => {
  localStorage.setItem(clientStateKeys.freePracticeTimer, '1')
  const { posts } = draftsServer({ [clientStateKeys.freePracticeTimer]: false })
  const { result } = renderHook(
    () => useClientState(clientStateKeys.freePracticeTimer, timerOptions),
    { wrapper: makeWrapper() },
  )
  await waitFor(() => expect(result.current.ready).toBe(true))
  expect(result.current.value).toBe(false)
  expect(posts).toEqual([])
  expect(localStorage.getItem(clientStateKeys.freePracticeTimer)).toBeNull()
})

it('writes changes to the drafts endpoint and keeps them for this session', async () => {
  const { posts } = draftsServer()
  const { result } = renderHook(
    () =>
      useClientState<string | null>(clientStateKeys.profileBatch, {
        fallback: null,
        fromLegacy: (raw) => raw || undefined,
      }),
    { wrapper: makeWrapper() },
  )
  await waitFor(() => expect(result.current.ready).toBe(true))
  expect(result.current.value).toBeNull()
  act(() => result.current.set('profile-batch-9'))
  await waitFor(() => expect(result.current.value).toBe('profile-batch-9'))
  await waitFor(() =>
    expect(posts).toEqual([{ key: clientStateKeys.profileBatch, value: 'profile-batch-9' }]),
  )
  act(() => result.current.set(null))
  await waitFor(() =>
    expect(posts.at(-1)).toEqual({ key: clientStateKeys.profileBatch, value: null }),
  )
})

it('does not show the onboarding again once the server remembers it was seen', async () => {
  draftsServer({ [clientStateKeys.onboardingSeen]: true })
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/'] })} />
    </QueryClientProvider>,
  )
  expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument()
  await new Promise((r) => setTimeout(r, 50))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
