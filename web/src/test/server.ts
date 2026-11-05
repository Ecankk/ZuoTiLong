import { vi } from 'vitest'
import type {
  AgentModels,
  BankCard,
  BankCollection,
  CatalogNode,
  Preferences,
  PreferencesChange,
  TasksResponse,
  TopicResponse,
} from '../api/types'
import {
  agentModels,
  paperList,
  papers,
  practiceDetails,
  practices,
  preferences,
  questionDetails,
  questions,
  tasks,
} from '../mocks/data'

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** 按 docs/frontend-api.md 的路径模拟本地服务，供页面测试使用。 */
export function mockServer(
  overrides: {
    tasks?: TasksResponse
    agentModels?: AgentModels[]
    preferences?: Preferences
    /** 测试自定义的路由，返回 undefined 时继续走默认处理 */
    routes?: (
      path: string,
      init: RequestInit | undefined,
      url: URL,
    ) => Response | Promise<Response> | undefined
  } = {},
) {
  let savedPreferences = overrides.preferences ?? preferences
  const modelReads = [...(overrides.agentModels ?? [agentModels])]
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const path = url.pathname
    const notFound = json({ error: 'not found' }, 404)
    const custom = await overrides.routes?.(path, init, url)
    if (custom) return custom
    if (path === '/api/profile')
      return json({
        free_practice: {
          total: 0,
          correct: 0,
          wrong: 0,
          pending: 0,
          independent_correct: 0,
          assisted_correct: 0,
        },
      })
    if (path === '/api/drafts') return json(init?.method === 'POST' ? { ok: true } : {})
    if (path === '/api/tasks') return json(overrides.tasks ?? tasks)
    if (path === '/api/agent/models')
      return json(modelReads.length > 1 ? modelReads.shift() : modelReads[0])
    if (path === '/api/preferences') {
      if (init?.method === 'POST') {
        const change = JSON.parse(String(init.body)) as PreferencesChange
        const profiles =
          change.execution_profiles === null
            ? preferences.execution_profiles
            : { ...savedPreferences.execution_profiles, ...change.execution_profiles }
        savedPreferences = { ...savedPreferences, ...change, execution_profiles: profiles }
      }
      return json(savedPreferences)
    }
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
    if (path === '/api/bank/collections') return json(bankCollections)
    if (path === '/api/bank') {
      const items = bankCards.filter(
        (card) =>
          card.collection_id === url.searchParams.get('collection') &&
          (!url.searchParams.get('q') ||
            (card.question_text ?? '').includes(url.searchParams.get('q')!)) &&
          (!url.searchParams.get('math_type') ||
            String(card.math_type) === url.searchParams.get('math_type')) &&
          (!url.searchParams.get('year') || card.year === url.searchParams.get('year')),
      )
      return json({ items, total: items.length, offset: 0, limit: 24, next_offset: null })
    }
    if (path === '/api/bank/topics')
      return json({
        catalog_revision: 'r1',
        items: url.searchParams
          .getAll('bank_id')
          .map((bank_id) => ({ bank_id, status: 'ready', topics: [catalogTopic] })),
      })
    if (path === '/api/knowledge/catalog/tree' || path === '/api/knowledge/catalog')
      return json({ release_id: 'r1', total: catalogNodes.length, items: catalogNodes })
    match = path.match(/^\/api\/knowledge\/topics\/([^/]+)$/)
    if (match) {
      const id = decodeURIComponent(match[1]) === 'old-id' ? 'a1' : decodeURIComponent(match[1])
      const found = catalogNodes.find((n) => n.id === id)
      return found ? json(topicDetail(found)) : notFound
    }
    if (path === '/api/practices') return json(practices)
    match = path.match(/^\/api\/practices\/([^/]+)$/)
    if (match) {
      const found = practiceDetails.find((p) => p.practice.id === match![1])
      return found ? json(found) : notFound
    }
    if (init?.method === 'POST') return json({ ok: true })
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

const r = String.raw

export const bankCards: BankCard[] = [
  {
    id: 'src-2026-7',
    math_type: 1,
    year: '2026',
    number: 7,
    can_view: true,
    reserved: false,
    reason: '',
    analysis_allowed: false,
    question_text: r`设 $f(x)=x^2$，求 $f'(1)$。`,
    analysis_text: r`$f'(x)=2x$，所以 $f'(1)=2$。`,
    question_type: '选择题',
    max_score: 5,
    collection_id: 'zhenti',
  },
  {
    id: 'math1-2020-01',
    math_type: 1,
    year: '2020',
    number: 1,
    can_view: false,
    reserved: true,
    reason: '这套试卷留作整卷自测',
    analysis_allowed: false,
    question_type: null,
    max_score: null,
    collection_id: 'zhenti',
  },
  {
    id: 'zy-q-3',
    math_type: 1,
    year: '',
    number: 0,
    can_view: true,
    reserved: false,
    reason: '',
    analysis_allowed: true,
    question_text: r`求 $\lim_{x\to0}\frac{\sin x}{x}$。`,
    question_type: '计算题',
    max_score: null,
    collection_id: 'zhangyu-1000',
    book: {
      title: '张宇1000题',
      edition: null,
      part: '强化篇',
      chapter: '第一章 函数极限',
      number: '3',
      locator: null,
    },
  },
  {
    id: 'zy-q-x',
    math_type: 1,
    year: '',
    number: 0,
    can_view: true,
    reserved: false,
    reason: '',
    analysis_allowed: true,
    question_text: '题号未知的教辅题',
    question_type: null,
    max_score: null,
    collection_id: 'zhangyu-1000',
    book: { title: null, edition: null, part: null, chapter: null, number: null, locator: null },
  },
]

export const bankCollections: BankCollection[] = [
  {
    id: 'zhenti',
    name: '真题',
    kind: 'exam',
    total: 2,
    ready: 2,
    math_types: [
      { math_type: 1, total: 2, ready: 2 },
      { math_type: 2, total: 0, ready: 0 },
    ],
  },
  {
    id: 'zhangyu-1000',
    name: '张宇1000题',
    kind: 'book',
    total: 2,
    ready: 2,
    math_types: [{ math_type: 1, total: 2, ready: 2 }],
  },
  { id: 'other', name: '其他', kind: 'other', total: 0, ready: 0 },
]

const catalogTopic = { topic_id: 'a1', name: '等价无穷小替换', role: 'primary' }

export const catalogNodes: CatalogNode[] = [
  { id: 'math1', parent_id: null, name: '高等数学', kind: 'subject', aliases: [] },
  { id: 'ch', parent_id: 'math1', name: '函数与极限', kind: 'chapter', aliases: [] },
  {
    id: 'a1',
    parent_id: 'ch',
    name: '等价无穷小替换',
    kind: 'atom',
    aliases: ['等价代换'],
    definition: '乘除因子中可用等价无穷小整体替换。',
    conditions: ['只在乘除中替换'],
    boundaries: ['加减中不能直接替换'],
  },
]

const topicDetail = (node: CatalogNode): TopicResponse => ({
  topic: {
    id: node.id,
    parent_id: node.parent_id,
    name: node.name,
    kind: node.kind,
    definition: node.definition ?? '',
    conditions: node.conditions ?? [],
    boundaries: node.boundaries ?? [],
  },
  performance: {
    state: '需要关注',
    state_reason: '最近两次都没做对',
    successes: 1,
    failures: 2,
    pending: 0,
    attempt_count: 3,
  },
  question_counts: { completed: 3, bank: 12 },
  collection_counts: [
    { collection_id: 'zhangyu-1000', bank: 5, ready: 5, completed: 0 },
    { collection_id: 'zhenti', bank: 9, ready: 9, completed: 3 },
  ],
  practice_counts: {
    pending: 0,
    grading: 0,
    graded: 0,
    needs_supplement: 0,
    inactive: 0,
    total: 0,
  },
})
