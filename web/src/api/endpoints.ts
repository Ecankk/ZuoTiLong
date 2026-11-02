/**
 * 数据接口，路径与参数见 docs/frontend-api.md。
 * 资源接口带强 ETag：浏览器按 Cache-Control: no-cache 自动带 If-None-Match 重新验证，
 * 304 时 fetch 拿到的是缓存内容，所以 query 失效后照常重取即可。
 */
import { ApiError, postJson, request } from './client'
import type {
  ImportResult,
  Page,
  Paper,
  PaperResponse,
  PracticeResponse,
  PracticesResponse,
  Preferences,
  QuestionResponse,
  QuestionsResponse,
  TasksResponse,
} from './types'

export type PracticeGrouping = 'topic' | 'paper'
export type PaperScope = '0' | '1'

const enc = encodeURIComponent

/** 404 表示资源不存在（如试卷已删除），页面按“没有找到”处理。 */
async function orNull<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export const endpoints = {
  tasks: () => request<TasksResponse>('/api/tasks'),
  papers: (archived: PaperScope) =>
    request<Page<Paper>>(`/api/papers?archived=${archived}&offset=0&limit=100`),
  paper: (paperId: string) => orNull(request<PaperResponse>(`/api/papers/${enc(paperId)}`)),
  paperQuestions: (paperId: string) =>
    request<QuestionsResponse>(`/api/papers/${enc(paperId)}/questions`),
  question: (questionId: string) =>
    orNull(request<QuestionResponse>(`/api/questions/${enc(questionId)}`)),
  practices: (groupBy: PracticeGrouping, includeInactive: boolean) =>
    request<PracticesResponse>(
      `/api/practices?group_by=${groupBy}&include_inactive=${includeInactive}&offset=0&limit=100`,
    ),
  practice: (practiceId: string) =>
    orNull(request<PracticeResponse>(`/api/practices/${enc(practiceId)}`)),
  preferences: () => request<Preferences>('/api/preferences'),
  /** 旧接口会整体覆盖偏好，所以带上其余字段一起提交 */
  savePreferences: (current: Preferences, change: Partial<Preferences>) => {
    const next = { ...current, ...change }
    return postJson<Preferences>('/api/preferences', {
      study_type: next.study_type,
      mask_same_type: next.mask_same_type,
      paper_marking_convention: next.paper_marking_convention,
      reserved: next.reserved,
    })
  },
  importPaper: (file: File, title: string, examDate: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('title', title)
    form.append('exam_date', examDate)
    return request<ImportResult>('/api/papers/import', { method: 'POST', body: form })
  },
}
