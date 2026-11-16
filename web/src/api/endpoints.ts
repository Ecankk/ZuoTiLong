/**
 * 数据接口。读取见 docs/frontend-api.md；写入沿用现有后端接口（app/api/*.py），契约尚未统一。
 * 资源接口带强 ETag：浏览器按 Cache-Control: no-cache 自动带 If-None-Match 重新验证，
 * 304 时 fetch 拿到的是缓存内容，所以 query 失效后照常重取即可。
 */
import { ApiError, postJson, request } from './client'
import type {
  AgentModels,
  AttemptBody,
  BankCard,
  AtomsResponse,
  BackupList,
  ExamDateFields,
  ImportDecisionRequest,
  ImportDecisionResponse,
  PaperDatesRequest,
  PaperDatesResponse,
  FeedbackReadRequest,
  Overview,
  ProfileBatch,
  ProfileBatchCreated,
  ProfileBatchRequest,
  Trends,
  BankCollection,
  HealthResponse,
  CollectionPackReport,
  PageImage,
  FreeAttempt,
  FreeAttemptBody,
  FreePractice,
  ProfileResponse,
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
  PreferencesChange,
  QuestionResponse,
  QuestionsResponse,
  TasksResponse,
  UploadedImage,
} from './types'

/** group_by：按考点 / 按试卷（画像题按批次成组） / 按来源 / 按画像批次 */
export type PracticeGrouping = 'topic' | 'paper' | 'source' | 'batch'

/** GET /api/practices 的可选筛选（app/api/frontend_resources.py 的实际参数） */
export type PracticeFilter = {
  /** paper：原卷练习；profile：画像选题；省略为两者合并 */
  source?: 'paper' | 'profile'
  batchId?: string
  status?: string
  paperId?: string
  topicId?: string
}
export type PaperScope = '0' | '1'
/** collection 必填：不同题集不混在一起浏览 */
export type BankFilter = {
  collection: string
  mathType: string
  year: string
  topic: string
  /** 题面文字搜索 */
  q?: string
}

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
  practices: (groupBy: PracticeGrouping, includeInactive: boolean, filter: PracticeFilter = {}) => {
    const query = new URLSearchParams({
      group_by: groupBy,
      include_inactive: String(includeInactive),
      offset: '0',
      limit: '100',
    })
    if (filter.source) query.set('source', filter.source)
    if (filter.batchId) query.set('batch_id', filter.batchId)
    if (filter.status) query.set('status', filter.status)
    if (filter.paperId) query.set('paper_id', filter.paperId)
    if (filter.topicId) query.set('topic_id', filter.topicId)
    return request<PracticesResponse>(`/api/practices?${query}`)
  },
  practice: (practiceId: string) =>
    orNull(request<PracticeResponse>(`/api/practices/${enc(practiceId)}`)),
  preferences: () => request<Preferences>('/api/preferences'),
  agentModels: () => request<AgentModels>('/api/agent/models'),
  /** 重新检查 AI 服务（只探测是否已安装、已登录，不创建任务） */
  connectAgent: () => postJson<unknown>('/api/agent/connect', {}),
  dataStatus: () => request<DataStatus>('/api/data/status'),
  /* ---------- 画像（B26） ---------- */
  profileOverview: () => request<Overview>('/api/profile/overview'),
  profileTrends: (weeks = 12) => request<Trends>(`/api/profile/trends?weeks=${weeks}`),
  profileAtoms: (nodeId: string, offset = 0, limit = 60) =>
    request<AtomsResponse>(
      `/api/profile/nodes/${enc(nodeId)}/atoms?offset=${offset}&limit=${limit}`,
    ),
  /** 按画像来一组：排一个 AI 选题任务，异步返回批次 */
  createProfileBatch: (body: ProfileBatchRequest) =>
    postJson<ProfileBatchCreated>('/api/practices/profile-batch', body),
  /** 已读回执：相同请求幂等，版本过期 409 */
  markFeedbackRead: (body: FeedbackReadRequest) => postJson<unknown>('/api/feedback/read', body),
  profileBatch: (batchId: string) =>
    request<ProfileBatch>(`/api/practices/profile-batches/${enc(batchId)}`),
  /** 服务健康和版本号（设置页“关于”用） */
  health: () => request<HealthResponse>('/api/health'),
  /** 已有的个人数据备份列表 */
  backups: () => request<BackupList>('/api/maintenance/backups'),
  /** 题库浏览（view=library）；考点筛选包含子考点，由后端处理 */
  bank: (filter: BankFilter, offset: number, limit: number) => {
    const query = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (filter.mathType) query.set('math_type', filter.mathType)
    if (filter.year) query.set('year', filter.year)
    if (filter.topic) query.set('topic_id', filter.topic)
    query.set('collection', filter.collection)
    if (filter.q) query.set('q', filter.q)
    return request<Page<BankCard>>(`/api/bank?${query}`)
  },
  freePractice: (bankId: string) => request<FreePractice>(`/api/bank/${enc(bankId)}/practice`),
  freeAttempts: (bankId: string, offset: number, limit: number) =>
    request<Page<FreeAttempt>>(
      `/api/bank/${enc(bankId)}/practice/attempts?offset=${offset}&limit=${limit}`,
    ),
  submitFreeAttempt: (bankId: string, body: FreeAttemptBody) =>
    postJson<FreeAttempt>(`/api/bank/${enc(bankId)}/practice/attempts`, body),
  draft: async <T>(key: string): Promise<T | null> =>
    (await request<{ value?: T }>(`/api/drafts?key=${enc(key)}`)).value ?? null,
  saveDraft: (key: string, value: unknown) => postJson('/api/drafts', { key, value }),
  profile: () => request<ProfileResponse>('/api/profile'),
  bankCollections: () => request<BankCollection[]>('/api/bank/collections'),
  bankTopics: (ids: string[]) =>
    request<BankTopics>(`/api/bank/topics?${ids.map((id) => `bank_id=${enc(id)}`).join('&')}`),
  /** 完整考点目录（只含名称、别名和层级），一次取全后在前端建树 */
  catalog: async (): Promise<CatalogNode[]> =>
    (await request<CatalogPage>('/api/knowledge/catalog/tree')).items,
  /** 历史考点 ID 由后端重定向，返回的 topic.id 可能与请求不同 */
  topic: (topicId: string) =>
    orNull(request<TopicResponse>(`/api/knowledge/topics/${enc(topicId)}`)),

  /* ---------- 设置 ---------- */
  /** 偏好接口只合并传入的字段 */
  savePreferences: (change: PreferencesChange) => postJson<Preferences>('/api/preferences', change),
  backup: () => postJson<{ path: string; files: number }>('/api/maintenance/backup', {}),

  /* ---------- 试卷 ---------- */
  /** 作答日期只在用户选择后才传；未选择时三个字段都不传（不默认今天） */
  importPaper: (file: File, title: string, date?: ExamDateFields) => {
    const form = new FormData()
    form.append('file', file)
    form.append('title', title)
    if (date) {
      if (date.exam_date) form.append('exam_date', date.exam_date)
      if (date.exam_date_precision) form.append('exam_date_precision', date.exam_date_precision)
      if (date.exam_date_unknown_reason)
        form.append('exam_date_unknown_reason', date.exam_date_unknown_reason)
    }
    return request<ImportResult>('/api/papers/import', { method: 'POST', body: form })
  },
  /** 批量修改作答日期（1–50 张） */
  updatePaperDates: (body: PaperDatesRequest) =>
    postJson<PaperDatesResponse>('/api/papers/dates', body),
  /** 重复上传的决定：这是重做 / 传错了撤回 */
  importDecision: (paperId: string, body: ImportDecisionRequest) =>
    postJson<ImportDecisionResponse>(`/api/papers/${enc(paperId)}/import-decision`, body),
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
    questions: {
      number: string
      question_ids: string[]
      split?: { page: number; y: number; lower_number: string }
    }[],
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
  /** 原卷整页图列表（调整切图用，接口形状待 B23 确定） */
  paperPages: (paperId: string) =>
    request<{ items: PageImage[] }>(`/api/papers/${enc(paperId)}/pages`),
  /** 只改这道题显示的原卷图（B23），坐标同拆题的 y */
  adjustRegions: (
    paperId: string,
    questionId: string,
    request_id: string,
    regions: { page: number; top: number; bottom: number }[],
  ) =>
    postJson(`/api/papers/${enc(paperId)}/questions/${enc(questionId)}/regions`, {
      confirmed: true,
      request_id,
      regions,
    }),
  previewCollectionPack: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<CollectionPackReport>('/api/library/collection-packs/preview', {
      method: 'POST',
      body: form,
    })
  },
  /** 长请求（真题包约 2.5 分钟），不设超时 */
  confirmCollectionPack: (report: Pick<CollectionPackReport, 'package_sha256' | 'plan_sha256'>) =>
    postJson<CollectionPackReport>('/api/library/collection-packs/confirm', {
      package_sha256: report.package_sha256,
      plan_sha256: report.plan_sha256,
      confirmed: true,
    }),
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
