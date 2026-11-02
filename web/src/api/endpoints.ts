/**
 * 数据获取入口，每个函数对应 docs/frontend-api.md 的一个接口（注释为真实路径）。
 * 当前返回本地演示数据；接入时把函数体换成 request(...)，页面不需要改动。
 */
import {
  home,
  papers,
  practiceDetails,
  practices,
  questionDetails,
  questions,
  revealedQuestions,
  tasks,
} from '../mocks/data'
import type {
  HomeData,
  PaperResponse,
  PracticeResponse,
  PracticesResponse,
  QuestionResponse,
  QuestionsResponse,
  TasksResponse,
} from './types'

const local = <T>(value: T): Promise<T> => Promise.resolve(structuredClone(value))

export type PracticeGrouping = 'topic' | 'paper'

function groupPracticesByPaper(source: PracticesResponse): PracticesResponse {
  const byPaper = new Map<string, PracticesResponse['items'][number]>()
  for (const card of source.items.flatMap((group) => group.items)) {
    const group = byPaper.get(card.paper_id) ?? {
      id: card.paper_id,
      label: card.paper_title,
      counts: { pending: 0, grading: 0, graded: 0, needs_supplement: 0, inactive: 0, total: 0 },
      items: [],
    }
    if (!group.items.some((item) => item.id === card.id)) {
      group.items.push(card)
      group.counts[card.status] += 1
      group.counts.total += 1
    }
    byPaper.set(card.paper_id, group)
  }
  const items = [...byPaper.values()]
  return { ...source, items, total: items.length }
}

export const endpoints = {
  /** GET /api/tasks */
  tasks: (): Promise<TasksResponse> => local(tasks),
  /** 契约未覆盖：首页规则留到后续批次 */
  home: (): Promise<HomeData> => local(home),
  /** GET /api/papers/{paper_id} */
  paper: (paperId: string): Promise<PaperResponse | null> =>
    local(papers.find((item) => item.paper.id === paperId) ?? null),
  /** GET /api/papers/{paper_id}/questions */
  paperQuestions: (paperId: string): Promise<QuestionsResponse> => {
    const items = questions.filter((question) => question.paper_id === paperId)
    return local({ items, total: items.length })
  },
  /** GET /api/questions/{question_id} */
  question: (questionId: string): Promise<QuestionResponse | null> =>
    local(questionDetails.find((item) => item.question.id === questionId) ?? null),
  /** GET /api/practices?group_by= */
  practices: (groupBy: PracticeGrouping): Promise<PracticesResponse> =>
    local(groupBy === 'paper' ? groupPracticesByPaper(practices) : practices),
  /** GET /api/practices/{practice_id} */
  practice: (practiceId: string): Promise<PracticeResponse | null> =>
    local(practiceDetails.find((item) => item.practice.id === practiceId) ?? null),
  /** 确认查看被遮挡的题目（真实接口沿用旧的确认查看入口，成功后重新获取练习） */
  revealQuestion: (practiceId: string): Promise<string | null> =>
    local(revealedQuestions[practiceId] ?? null),
}
