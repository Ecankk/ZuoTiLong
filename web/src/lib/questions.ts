import type { QuestionSummary } from '../api/types'

export type QuestionGroup = { label: string | null; questions: QuestionSummary[] }

const sectionOrder = ['选择题', '填空题', '解答题']

const byNumber = (a: QuestionSummary, b: QuestionSummary) => Number(a.number) - Number(b.number)

/**
 * 题号条分组：题型取自匹配到的题库（question_type）。只要有一题题型缺失或无法识别，
 * 就只按题号排列，不猜测题型。
 */
export function groupQuestions(questions: QuestionSummary[]): QuestionGroup[] {
  const sorted = [...questions].sort(byNumber)
  if (sorted.some((question) => !sectionOrder.includes(question.question_type ?? ''))) {
    return [{ label: null, questions: sorted }]
  }
  return sectionOrder
    .map((label) => ({
      label,
      questions: sorted.filter((question) => question.question_type === label),
    }))
    .filter((group) => group.questions.length > 0)
}
