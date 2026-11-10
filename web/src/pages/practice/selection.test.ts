import { expect, it } from 'vitest'
import type { PracticeCard, PracticeGroup } from '../../api/types'
import { practices } from '../../mocks/data'
import {
  buildSections,
  filterSections,
  nextTodo,
  pickSelected,
  practiceBucket,
  practiceOrigin,
  splitQuestionText,
  usefulAnalysis,
} from './selection'

const base = practices.items[0].items[0]
const card = (id: string, status: PracticeCard['status'], change: Partial<PracticeCard> = {}) =>
  ({
    ...base,
    id,
    status,
    latest_attempt_id: status === 'pending' ? null : `attempt-${id}`,
    ...change,
  }) as PracticeCard
const group = (id: string, items: PracticeCard[]): PracticeGroup => ({
  id,
  label: id,
  items,
  counts: { pending: 0, grading: 0, graded: 0, needs_supplement: 0, inactive: 0, total: 0 },
})

it('sorts practices into 未做 / 待批改 / 做错 / 做对', () => {
  const results = { right: 'correct', wrong: 'wrong', half: 'partial', unsure: 'unknown' } as const
  expect(practiceBucket(card('a', 'pending'), results)).toBe('todo')
  // 提交了但还没批改的仍是 pending 状态
  expect(practiceBucket(card('b', 'pending', { latest_attempt_id: 'x' }), results)).toBe('waiting')
  expect(practiceBucket(card('c', 'grading'), results)).toBe('waiting')
  expect(practiceBucket(card('d', 'needs_supplement'), results)).toBe('waiting')
  expect(practiceBucket(card('right', 'graded'), results)).toBe('right')
  expect(practiceBucket(card('wrong', 'graded'), results)).toBe('wrong')
  expect(practiceBucket(card('half', 'graded'), results)).toBe('wrong')
  expect(practiceBucket(card('unsure', 'graded'), results)).toBe('waiting')
  // 对错还没读到时不归类，也不当成没做
  expect(practiceBucket(card('later', 'graded'), results)).toBeUndefined()
  expect(practiceBucket(card('off', 'inactive'), results)).toBeUndefined()
})

it('derives the source from an optional origin field and hides it when unknown', () => {
  expect(practiceOrigin(card('a', 'pending'))).toBe('paper')
  expect(practiceOrigin(card('a', 'pending', { origin: 'profile_batch' } as never))).toBe('profile')
  expect(practiceOrigin(card('a', 'pending', { origin: 'free_practice' } as never))).toBe('free')
  expect(practiceOrigin(card('a', 'pending', { paper_id: '' }))).toBeUndefined()
})

it('filters by status and source but keeps the current practice', () => {
  const sections = buildSections(
    [
      group('t1', [card('a', 'pending'), card('b', 'graded')]),
      group('t2', [card('c', 'pending', { origin: 'profile' } as never)]),
    ],
    'topic',
  )
  const results = { b: 'correct' as const }
  const right = filterSections(sections, { status: 'right' }, results)
  expect(right.flatMap((s) => s.rows.map((r) => r.card.id))).toEqual(['b'])
  const profile = filterSections(sections, { source: 'profile' }, results, 'a')
  expect(profile.flatMap((s) => s.rows.map((r) => r.card.id))).toEqual(['a', 'c'])
  const search = filterSections(sections, { query: 'T2' }, results)
  expect(search.map((s) => s.group.id)).toEqual(['t2'])
})

it('finds the next unfinished practice after the current one, wrapping around', () => {
  const sections = buildSections(
    [
      group('t1', [card('a', 'pending'), card('b', 'graded')]),
      group('t2', [card('c', 'pending'), card('d', 'grading')]),
    ],
    'topic',
  )
  expect(nextTodo(sections, 'a', {})?.id).toBe('c')
  expect(nextTodo(sections, 'c', {})?.id).toBe('a')
  expect(nextTodo(sections, 'b', {})?.id).toBe('c')
  expect(nextTodo(buildSections([group('t', [card('a', 'pending')])], 'topic'), 'a', {})).toBe(
    undefined,
  )
})

it('picks the first unfinished practice of a paper when asked', () => {
  const groups = [
    group('t1', [
      card('a', 'graded', { paper_id: 'p1' }),
      card('b', 'pending', { paper_id: 'p2' }),
    ]),
    group('t2', [card('c', 'pending', { paper_id: 'p1' })]),
  ]
  expect(pickSelected(groups, { paper: 'p1' })).toBe('c')
  expect(pickSelected(groups, { item: 'a' })).toBe('a')
  expect(pickSelected(groups, {})).toBe('b')
})

it('hides navigation and placeholder texts but keeps real content', () => {
  expect(
    splitQuestionText({ question_text: '2022 数学三 第22题 · 参数估计', question_image: '/q.png' }),
  ).toEqual({ text: null, chapter: '参数估计' })
  // 没有题图时文字就是题干
  expect(splitQuestionText({ question_text: '2022 数学三 第22题 · 参数估计' }).text).toBe(
    '2022 数学三 第22题 · 参数估计',
  )
  expect(splitQuestionText({ question_text: '求极限 $x$', question_image: '/q.png' }).text).toBe(
    '求极限 $x$',
  )
  expect(usefulAnalysis('参考解析见原图')).toBeNull()
  expect(usefulAnalysis('参考解析见原图。')).toBeNull()
  expect(usefulAnalysis('由洛必达法则')).toBe('由洛必达法则')
})
