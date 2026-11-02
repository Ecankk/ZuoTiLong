import { expect, it } from 'vitest'
import type { QuestionSummary } from '../api/types'
import { groupQuestions } from './questions'

const q = (number: string, question_type: string | null): QuestionSummary => ({
  id: `q${number}`,
  paper_id: 'p',
  number,
  question_type,
  max_score: null,
  score_earned: null,
  correctness: 'correct',
  review_state: 'done',
  analysis_available: true,
  matched_bank_id: null,
})

it('groups matched questions by type in exam order', () => {
  const groups = groupQuestions([q('17', '解答题'), q('2', '选择题'), q('11', '填空题')])
  expect(groups.map((g) => [g.label, g.questions.map((x) => x.number)])).toEqual([
    ['选择题', ['2']],
    ['填空题', ['11']],
    ['解答题', ['17']],
  ])
})

it('falls back to plain numeric order when any type is missing or unknown', () => {
  for (const odd of [null, '证明题']) {
    const groups = groupQuestions([q('10', '选择题'), q('2', odd), q('1', '选择题')])
    expect(groups).toEqual([
      { label: null, questions: [q('1', '选择题'), q('2', odd), q('10', '选择题')] },
    ])
  }
})
