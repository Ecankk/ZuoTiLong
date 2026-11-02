import { vi } from 'vitest'
import type { TasksResponse } from '../api/types'
import {
  paperList,
  papers,
  practiceDetails,
  practices,
  preferences,
  questionDetails,
  questions,
  tasks,
} from '../mocks/data'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** 按 docs/frontend-api.md 的路径模拟本地服务，供页面测试使用。 */
export function mockServer(overrides: { tasks?: TasksResponse } = {}) {
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const path = url.pathname
    const notFound = json({ error: 'not found' }, 404)
    if (path === '/api/tasks') return json(overrides.tasks ?? tasks)
    if (path === '/api/preferences')
      return json(init?.method === 'POST' ? JSON.parse(String(init.body)) : preferences)
    if (path === '/api/papers') return json(paperList)
    let match = path.match(/^\/api\/papers\/([^/]+)\/questions$/)
    if (match) {
      const items = questions.filter((q) => q.paper_id === match![1])
      return json({ items, total: items.length })
    }
    match = path.match(/^\/api\/papers\/([^/]+)$/)
    if (match) {
      const found = papers.find((p) => p.paper.id === match![1])
      return found ? json(found) : notFound
    }
    match = path.match(/^\/api\/questions\/([^/]+)$/)
    if (match) {
      const found = questionDetails.find((q) => q.question.id === match![1])
      return found ? json(found) : notFound
    }
    if (path === '/api/practices') return json(practices)
    match = path.match(/^\/api\/practices\/([^/]+)$/)
    if (match) {
      const found = practiceDetails.find((p) => p.practice.id === match![1])
      return found ? json(found) : notFound
    }
    return notFound
  })
  vi.stubGlobal('fetch', fetch)
  vi.stubGlobal(
    'EventSource',
    class {
      addEventListener() {}
      close() {}
    },
  )
  return fetch
}
