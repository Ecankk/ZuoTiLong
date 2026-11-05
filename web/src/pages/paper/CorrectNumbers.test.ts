import { expect, it } from 'vitest'
import type { QuestionSummary } from '../../api/types'
import { buildCorrection } from './CorrectNumbers'

const q = (id: string, number: string) => ({ id, number }) as QuestionSummary

it('renumbers, merges fragments into the previous question and deletes stray parts', () => {
  const result = buildCorrection([
    { question: q('a', '1'), number: '1', action: 'keep' },
    { question: q('b', '2'), number: '2', action: 'merge' },
    { question: q('c', '3'), number: '2', action: 'keep' },
    { question: q('d', '4'), number: '4', action: 'delete' },
  ])
  expect(result).toEqual({
    groups: [
      { number: '1', question_ids: ['a', 'b'] },
      { number: '2', question_ids: ['c'] },
    ],
    deleted: ['d'],
    problem: null,
  })
})

it('rejects duplicate or empty numbers', () => {
  const rows = [
    { question: q('a', '1'), number: '1', action: 'keep' as const },
    { question: q('b', '2'), number: '1', action: 'keep' as const },
  ]
  expect(buildCorrection(rows).problem).toBe('题号有重复，请检查')
  rows[1].number = ' '
  expect(buildCorrection(rows).problem).toBe('每道题都需要题号')
})

const split = { page: 1, y: 250.5, lower_number: '2', regionIndex: 0, d: 100, H: 400 }

it('sends a split with the upper and lower numbers and checks them for duplicates', () => {
  const rows = [
    { question: q('a', '1'), number: '1', action: 'keep' as const, split },
    { question: q('c', '3'), number: '3', action: 'keep' as const },
  ]
  expect(buildCorrection(rows)).toEqual({
    groups: [
      { number: '1', question_ids: ['a'], split: { page: 1, y: 250.5, lower_number: '2' } },
      { number: '3', question_ids: ['c'] },
    ],
    deleted: [],
    problem: null,
  })
  rows[1].number = '2'
  expect(buildCorrection(rows).problem).toBe('题号有重复，请检查')
})

it('does not allow merging another part into a question being split', () => {
  const result = buildCorrection([
    { question: q('a', '1'), number: '1', action: 'keep', split },
    { question: q('b', '2'), number: '2', action: 'merge' },
  ])
  expect(result.problem).toMatch(/要拆开的题不能同时再并入其他部分/)
})
