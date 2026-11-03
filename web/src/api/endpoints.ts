/**
 * 数据接口。读取见 docs/frontend-api.md；写入沿用现有后端接口（app/api/*.py），契约尚未统一。
 * 资源接口带强 ETag：浏览器按 Cache-Control: no-cache 自动带 If-None-Match 重新验证，
 * 304 时 fetch 拿到的是缓存内容，所以 query 失效后照常重取即可。
 */
import { ApiError, postJson, request } from './client'
import type {
  AttemptBody,
  BankCard,
  BankTopics,
  CatalogNode,
  CatalogPage,
  DataStatus,
  TopicResponse,
  ImportResult,
  MathType,
  Page,
  Paper,
  PaperResponse,
  PaperSummaryResponse,
  PracticeResponse,
  PracticesResponse,
  Preferences,
  QuestionResponse,
  QuestionsResponse,
  TasksResponse,
  UploadedImage,
} from './types'

export type PracticeGrouping = 'topic' | 'paper'
export type PaperScope = '0' | '1'
export type BankFilter = { mathType: string; year: string; topic: string }

const enc = encodeURIComponent

/** 每次用户发起的任务带一个新的请求编号，后端据此去重。 */
export const requestId = () => crypto.randomUUID()

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
  /* ---------- 读取 ---------- */
  tasks: () => request<TasksResponse>('/api/tasks'),
  papers: (archived: PaperScope) =>
    request<Page<Paper>>(`/api/papers?archived=${archived}&offset=0&limit=100`),
  paper: (paperId: string) => orNull(request<PaperResponse>(`/api/papers/${enc(paperId)}`)),
  paperQuestions: (paperId: string) =>
    request<QuestionsResponse>(`/api/papers/${enc(paperId)}/questions`),
  paperSummary: (paperId: string) =>
    request<PaperSummaryResponse>(`/api/papers/${enc(paperId)}/summary`),
  question: (questionId: string) =>
    orNull(request<QuestionResponse>(`/api/questions/${enc(questionId)}`)),
  practices: (groupBy: PracticeGrouping, includeInactive: boolean) =>
    request<PracticesResponse>(
      `/api/practices?group_by=${groupBy}&include_inactive=${includeInactive}&offset=0&limit=100`,
    ),
  practice: (practiceId: string) =>
    orNull(request<PracticeResponse>(`/api/practices/${enc(practiceId)}`)),
  preferences: () => request<Preferences>('/api/preferences'),
  dataStatus: () => request<DataStatus>('/api/data/status'),
  /** 题库浏览（view=library）；考点筛选包含子考点，由后端处理 */
  bank: (filter: BankFilter, offset: number, limit: number) => {
    const query = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (filter.mathType) query.set('math_type', filter.mathType)
    if (filter.year) query.set('year', filter.year)
    if (filter.topic) query.set('topic_id', filter.topic)
    return request<Page<BankCard>>(`/api/bank?${query}`)
  },
  bankTopics: (ids: string[]) =>
    request<BankTopics>(`/api/bank/topics?${ids.map((id) => `bank_id=${enc(id)}`).join('&')}`),
  /** 完整考点目录：接口每页最多 100 项，分页取全后在前端建树 */
  catalog: async (): Promise<CatalogNode[]> => {
    const first = await request<CatalogPage>('/api/knowledge/catalog?limit=100&offset=0')
    const rest = await Promise.all(
      Array.from({ length: Math.max(0, Math.ceil(first.total / 100) - 1) }, (_, i) =>
        request<CatalogPage>(`/api/knowledge/catalog?limit=100&offset=${(i + 1) * 100}`),
      ),
    )
    return [first, ...rest].flatMap((page) => page.items)
  },
  /** 历史考点 ID 由后端重定向，返回的 topic.id 可能与请求不同 */
  topic: (topicId: string) =>
    orNull(request<TopicResponse>(`/api/knowledge/topics/${enc(topicId)}`)),

  /* ---------- 设置 ---------- */
  /** 偏好接口只合并传入的字段 */
  savePreferences: (change: Partial<Preferences>) =>
    postJson<Preferences>('/api/preferences', change),
  backup: () => postJson<{ path: string; files: number }>('/api/maintenance/backup', {}),

  /* ---------- 试卷 ---------- */
  importPaper: (file: File, title: string, examDate: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('title', title)
    form.append('exam_date', examDate)
    return request<ImportResult>('/api/papers/import', { method: 'POST', body: form })
  },
  /** 已有分析时需要 confirmed=true（重新分析，旧报告保留） */
  analyzePaper: (paperId: string, confirmed: boolean) =>
    postJson<{ job_id: string }>(`/api/papers/${enc(paperId)}/analyze`, { confirmed }),
  archivePaper: (paperId: string) =>
    postJson(`/api/papers/${enc(paperId)}/archive`, { confirmed: true }),
  restorePaper: (paperId: string) =>
    postJson(`/api/papers/${enc(paperId)}/restore`, { confirmed: true }),
  scorePaper: (paperId: string, score: number, totalScore: number, mathType: MathType) =>
    postJson(`/api/papers/${enc(paperId)}/score`, {
      score,
      total_score: totalScore,
      math_type: mathType,
      confirmed: true,
    }),
  /** 原卷没能定位题目时，按用户填写的题号建立题目 */
  confirmNumbers: (paperId: string, numbers: string[], scores: number[], subject: string) =>
    postJson(`/api/papers/${enc(paperId)}/confirm`, { numbers, scores, subject }),
  summarizePaper: (paperId: string) =>
    postJson(`/api/papers/${enc(paperId)}/resummarize`, { confirmed: true }),
  /** 返回任务摘要（同 GET /api/tasks） */
  preparePractice: (paperId: string) =>
    postJson<TasksResponse>(`/api/papers/${enc(paperId)}/prepare-practice`, {
      request_id: requestId(),
    }),
  /**
   * 纠正分析前的切分：questions 必须覆盖本卷全部题目（单个 ID 为重新编号，多个为合并），
   * 误切的题放进 deleteIds。后端会保存纠正前的切分。
   */
  correctQuestions: (
    paperId: string,
    questions: { number: string; question_ids: string[] }[],
    deleteIds: string[],
  ) =>
    postJson<{ question_ids: string[]; deleted_question_ids: string[] }>(
      `/api/papers/${enc(paperId)}/questions/correct`,
      { confirmed: true, questions, delete_question_ids: deleteIds },
    ),
  reviewQuestion: (questionId: string, reportId: string, note: string) =>
    postJson(`/api/questions/${enc(questionId)}/review`, {
      request_id: requestId(),
      report_id: reportId,
      note,
      image_ids: [],
      image_roles: {},
    }),

  /* ---------- 练习 ---------- */
  /** 确认查看题目或解析，会记录曝光 */
  reveal: (bankId: string, role: 'question' | 'analysis') =>
    postJson(`/api/bank/${enc(bankId)}/reveal`, { role, confirmed: true }),
  uploadImages: (files: File[]) => {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    return request<{ images: UploadedImage[] }>('/api/answer-images', {
      method: 'POST',
      body: form,
    })
  },
  submitAttempt: (practiceId: string, body: AttemptBody) =>
    postJson<{ attempt_id: string }>(`/api/probes/${enc(practiceId)}/submit`, body),
  supplementAttempt: (attemptId: string, body: AttemptBody) =>
    postJson(`/api/attempts/${enc(attemptId)}/supplement`, body),
  /** 作答已保存但没有批改结果时，重新排入批改 */
  requestGrading: (practiceId: string, attemptId: string) =>
    postJson(`/api/probes/${enc(practiceId)}/feedback`, { attempt_id: attemptId }),

  /* ---------- 后台任务 ---------- */
  taskAction: (jobId: string, action: 'retry' | 'cancel') =>
    postJson<TasksResponse>(`/api/tasks/${enc(jobId)}/action`, { action }),
}
