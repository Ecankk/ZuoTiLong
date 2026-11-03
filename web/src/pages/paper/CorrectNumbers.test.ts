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
