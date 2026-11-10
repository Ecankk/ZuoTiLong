/**
 * 前端数据形状，字段名与 docs/frontend-api.md（B3 契约）一致。
 * 标“契约未覆盖”的类型是本批页面需要、但契约明确留到后续批次的部分，接口确定后再对齐。
 */

/* ---------- 公共 ---------- */

export type Page<T> = {
  items: T[]
  total: number
  offset: number
  limit: number
  next_offset: number | null
}

export type MathType = 1 | 2 | 3

export type Correctness = 'correct' | 'wrong' | 'partial' | 'unknown'

export type Counts = Record<Correctness | 'total', number>

export type TopicRef = { topic_id: string; name: string }

/* ---------- 试卷与逐题分析 ---------- */

export type Paper = {
  id: string
  title: string
  exam_date: string | null
  score: number | null
  total_score: number
  score_confirmed: boolean
  archived_at: string | null
  created_at: string
  updated_at: string | null
  analysis_status: string
  counts: Counts
}

export type AnalysisState = {
  report_id: string | null
  completion: string | null
  review_status: string | null
  summary: string
  limitations: string[]
}

export type PracticeCounts = {
  pending: number
  grading: number
  graded: number
  needs_supplement: number
  inactive: number
  total: number
}

export type PaperResponse = {
  paper: Paper
  analysis: AnalysisState
  weak_topics: TopicRef[]
  practice_counts: PracticeCounts
  summary_status: 'missing' | 'available'
  actions: string[]
}

export type QuestionSummary = {
  id: string
  paper_id: string
  number: string
  /** 来自匹配到的题库 metadata；无法匹配时为 null，不按题号猜测 */
  question_type: string | null
  max_score: number | null
  score_earned: number | null
  correctness: Correctness
  review_state: string
  analysis_available: boolean
  matched_bank_id: string | null
}

export type QuestionsResponse = { items: QuestionSummary[]; total: number }

export type Region = { page: number; bbox: [number, number, number, number]; role: string }

export type FirstError = { stage: string; step: string; evidence: string }

export type Diagnosis = {
  stem: string
  observation: string
  correctness: Correctness
  answer_evidence?: {
    student_work: string
    student_state: 'visible' | 'not_attempted' | 'unreadable'
    marking: string
    marking_note: string
  }
  correct_parts?: string[]
  first_error?: FirstError | null
  solution_guide?: {
    entry_point: string
    strategy: string
    key_steps: string[]
    pitfalls: string[]
  } | null
  reference_answer?: string
  reference_reasoning?: string
  hypotheses?: {
    id: string
    label: string
    evidence: string
    alternative: string
    correction: string
  }[]
  cause_summary?: string
  knowledge?: string[]
  fingerprint?: Record<string, unknown>
}

/** 逐步对照。契约未覆盖（capabilities.step_comparison=false），字段为前端暂定 */
export type StepComparison = {
  yours: { text: string; mark?: 'error' | 'affected' }[]
  expected: { text: string; mark?: 'fix' }[]
  explanation: string
}

export type QuestionResponse = {
  question: QuestionSummary & { stem: string; regions: Region[] }
  diagnosis: Diagnosis | null
  topics: TopicRef[]
  evidence_urls: string[]
  /** 每段切图的图片和换算参数（B20），用于在图上选择拆分位置 */
  evidence_regions?: EvidenceRegion[]
  practice_counts: PracticeCounts
  previous_id: string | null
  next_id: string | null
  capabilities: { step_comparison: boolean }
  /** 仅在 capabilities.step_comparison 为 true 时提供（契约未覆盖） */
  step_comparison?: StepComparison
}

/* ---------- 练习 ---------- */

export type PracticeStatus = 'pending' | 'grading' | 'graded' | 'needs_supplement' | 'inactive'

export type Access = {
  id: string
  /** 题集题（如教辅）没有真题身份：这三项可能缺失、为空或为 0 */
  math_type?: MathType | 0 | null
  year?: string | null
  number?: number | null
  reserved: boolean
  can_view: boolean
  confirmed: boolean
  cross_checked: boolean
  masked: boolean
  analysis_allowed: boolean
  reason: string
}

export type PracticeCard = {
  id: string
  paper_id: string
  paper_title: string
  question_id: string
  bank_id: string
  status: PracticeStatus
  created_at: string
  goal_ids: string[]
  topics: TopicRef[]
  access: Access
  latest_attempt_id: string | null
}

export type PracticeGroup = {
  id: string
  label: string
  counts: PracticeCounts
  items: PracticeCard[]
}

export type PracticesResponse = Page<PracticeGroup> & { counts: PracticeCounts }

export type Assessment = {
  correct: boolean | null
  /** 已保存批改对象里的结果字段（契约未列出，存在时优先使用） */
  answer_status?: string
  feedback: string
  observations?: { step: string; stage: string; status: string; evidence: string }[]
  first_error?: FirstError | null
  possible_causes?: {
    id: string
    label: string
    evidence: string
    alternative: string
    correction: string
  }[]
  reference_reasoning?: string
  next_step?: string
  needs_material?: string[]
}

export type Attempt = {
  id: string
  probe_id: string
  response: string
  image_ids: string[]
  image_roles: Record<string, string>
  answer_exposed: boolean
  elapsed_seconds: number | null
  created_at: string
  assessment: Assessment | null
}

export type PracticeAction = 'submit' | 'supplement' | 'reveal_question' | 'reveal_analysis'

export type PracticeResponse = {
  practice: PracticeCard
  is_current: boolean
  review_reason: string | null
  question: {
    question_text?: string
    question_image?: string
    analysis_text?: string
    analysis_image?: string
    expected?: string
    solution_note?: string
  } | null
  goals: Record<string, unknown>[]
  selection_reason: string | null
  latest_attempt: Attempt | null
  actions: PracticeAction[]
}

/* ---------- 任务摘要 ---------- */

export type Task = {
  id: string
  kind: string
  paper_id: string | null
  paper_title: string | null
  attempt_id: string | null
  status: 'queued' | 'running' | 'completed' | 'blocked' | 'failed' | 'cancelled'
  progress: { message: string }
  error: string | null
  created_at: string
  updated_at: string
  allowed_actions: ('retry' | 'cancel')[]
}

export type TasksResponse = Page<Task> & {
  status: 'idle' | 'connecting' | 'running' | 'attention_required' | 'agent_unavailable'
  availability: {
    status: 'available' | 'checking' | 'unavailable'
    reason: null | 'not_installed' | 'not_logged_in' | 'disabled' | 'other'
    message: string
  }
  active: Task | null
  queued_count: number
  failed_count: number
}

/* ---------- 偏好设置（沿用旧接口 GET/POST /api/preferences） ---------- */

export type Preferences = {
  study_type: MathType
  mask_same_type: boolean
  paper_marking_convention: string
  reserved: { math_type: MathType; year: string }[]
  /** 判断类任务（分析试卷、单题复核、批改作答）和整理类任务（选择练习、整理考点、总结）用的模型 */
  execution_profiles: Record<ProfileTier, ExecutionProfile>
  /** 画像和考点表现是否计入自由练习，默认计入 */
  include_free_practice?: boolean
}

/* ---------- 题库题目自由练习（B18） ---------- */

export type FreePracticeCounts = {
  total: number
  correct: number
  wrong: number
  pending: number
  independent_correct: number
  assisted_correct: number
}

/** B20 起老图片题的文字可能是 null，只显示图片 */
export type FreeQuestion = { question_text?: string | null; question_image?: string | null }
export type FreeReference = {
  answer_text?: string | null
  answer_image?: string | null
  analysis_text?: string | null
  analysis_image?: string | null
  errata?: Erratum[]
}

export type FreeAttempt = {
  id: string
  bank_id: string
  source: 'free_practice'
  request_id?: string
  question_type: string | null
  collection_id: string
  response: string
  choice?: string | null
  image_ids: string[]
  image_roles: Record<string, string>
  answer_exposed: boolean
  elapsed_seconds: number | null
  created_at: string
  assessment: Assessment | null
  job: { id: string; status: string } | null
  /** 这次作答自己的固定快照；未判定时 reference 为 null */
  materials: { question: FreeQuestion; reference: FreeReference | null }
}

/** GET /api/bank/{id}/practice */
export type FreePractice = {
  bank_id: string
  question_type: string | null
  collection_id: string
  question: FreeQuestion
  source: {
    math_type: MathType | 0 | null
    year: string | null
    number: number | null
    question_type?: string | null
    max_score?: number | null
    book?: BookLocator
  }
  reference: FreeReference | null
  actions: ('submit' | 'reveal_analysis')[]
  latest_attempt: FreeAttempt | null
  attempt_count: number
}

export type FreeAttemptBody = {
  request_id: string
  response: string
  choice?: string
  image_ids: string[]
  image_roles: Record<string, ImageRole>
  answer_exposed: boolean
  elapsed_seconds: number
}

/** GET /api/profile 中前端用到的部分 */
export type ProfileResponse = { free_practice?: FreePracticeCounts }

export type ProfileTier = 'judgment' | 'organization'
export type ExecutionProfile = { model: string; effort: string }

/** POST /api/preferences 的请求体：按字段合并；execution_profiles 为 null 时恢复默认 */
export type PreferencesChange = Partial<Omit<Preferences, 'execution_profiles'>> & {
  execution_profiles?: Partial<Record<ProfileTier, ExecutionProfile>> | null
}

/** GET /api/agent/models：本机 Codex 可用的模型 */
export type AgentModels = {
  status: 'available' | 'checking' | 'unavailable'
  reason: null | 'not_installed' | 'not_logged_in' | 'other' | 'disabled'
  message: string
  items: { id: string; name: string; efforts: string[] }[]
}

/** POST /api/papers/import 的返回中前端用到的部分 */
export type ImportResult = { paper: { id: string }; analysis_warning?: string }

/* ---------- 写入（沿用现有后端接口，契约尚未统一） ---------- */

/** GET /api/papers/{paper_id}/summary */
export type PaperSummaryResponse = {
  status: 'missing' | 'available'
  result_id: string | null
  created_at: string | null
  summary: {
    overview?: string
    key_findings?: (string | { text: string })[]
    improvements?: (string | { text: string })[]
    next_actions?: (string | { text: string })[]
    limitations?: string[]
  } | null
}

/** POST /api/answer-images */
export type UploadedImage = { id: string; url: string; width?: number; height?: number }

export type ImageRole = 'own_work' | 'marking' | 'external_solution'

export type AttemptBody = {
  response: string
  image_ids: string[]
  image_roles: Record<string, ImageRole>
  answer_exposed: boolean
  request_id: string
}

/** GET /api/health：服务是否在线、版本号 */
export type HealthResponse = { ok: boolean; app: string; version: string; data_id?: string }

/** GET /api/maintenance/backups：已有的个人数据备份，新的在前 */
export type BackupList = { backups: { name: string; bytes: number }[] }

/** GET /api/data/status */
export type DataStatus = {
  data_dir: string
  library_dir: string
  library_exists: boolean
  library_env_override: boolean
  databases: Record<'learning' | 'library' | 'session', { bytes: number; exists: boolean }>
  invalid_file_references: {
    count: number
    examples: { table: string; field: string; relative?: string }[]
  }
  last_backup_at: string | null
  path_migration: {
    pending: boolean
    ready_count: number
    unresolved_count: number
    historical_reference_count: number
    plan_sha256: string
  }
}

/* ---------- 题库与考点 ---------- */

/** GET /api/bank?…&offset&limit 的一项（public_bank view=library + 题型/分值） */
export type BankCard = {
  id: string
  math_type: MathType | 0 // 0：没有真题身份（教辅题等）
  year: string
  number: number
  can_view: boolean
  reserved: boolean
  reason: string
  analysis_allowed: boolean
  stem?: string
  question_text?: string
  analysis_text?: string
  tags?: string[]
  question_image?: string
  analysis_image?: string
  question_type: string | null
  max_score: number | null
  /** 所属题集；教辅题另有书内定位（真题没有） */
  collection_id: string
  book?: BookLocator
  /** 勘误记录（无勘误为空）；答案/解析类依据要在答案可见后才能展开 */
  errata?: Erratum[]
}

export type Erratum = { role: string; reason: string; evidence: string }

/** 导入题集包：预演与确认返回同一结构，确认后 applied=true 并带备份信息 */
export type CollectionPackReport = {
  package_sha256: string
  plan_sha256: string
  package_version?: string
  created_at?: string
  sources?: { source_id: string; revision: string }[]
  trust_notice?: string
  collection: { id: string; name: string; kind: string }
  counts: {
    total: number
    ready: number
    needs_review: number
    needs_catalog: number
    unannotated: number
  }
  added: string[]
  updated: string[]
  unchanged: string[]
  catalog: { status: 'current' | 'upgrade' | 'keep_current' | 'conflict' }
  collection_conflicts: (
    | { collection_id: string; existing_kind: string; requested_kind: string }
    | { bank_id: string; existing: string; requested: string }
  )[]
  applied: boolean
  backup?: { path: string; files?: number }
}

/** 教辅题的书内定位，各字段都可能为空 */
export type BookLocator = {
  title: string | null
  edition: string | null
  part: string | null
  chapter: string | null
  number: string | null
  locator: string | null
}

/** 原卷整页图（调整切图用）；坐标换算同切图，原点为 0（接口待 B23 确定） */
export type PageImage = {
  page: number
  image_url: string
  image_width: number
  image_height: number
  scale: number
}

export type EvidenceRegion = {
  region_index: number
  page: number
  bbox: number[]
  image_url: string
  image_width: number
  image_height: number
  image_origin: [number, number]
  scale: number
}

/** GET /api/bank/collections 的一项，已按显示顺序返回 */
export type BankCollection = {
  id: string
  name: string
  kind: 'exam' | 'book' | 'other' | 'example'
  total: number
  ready: number
  /** 各数学类别的题数，稀疏（没有题的类别不出现）。B16 起提供 */
  math_types?: { math_type: MathType; total: number; ready: number }[]
}

/** GET /api/bank/topics?bank_id=… */
export type BankTopics = {
  catalog_revision: string | null
  items: {
    bank_id: string
    status: string
    topics: { topic_id: string; name: string; role: string }[]
  }[]
}

/** GET /api/knowledge/catalog 的一项 */
export type CatalogNode = {
  id: string
  parent_id: string | null
  name: string
  kind: 'subject' | 'chapter' | 'topic' | 'atom' | string
  aliases: string[]
  definition?: string
  conditions?: string[]
  boundaries?: string[]
}

export type CatalogPage = { release_id: string | null; total: number; items: CatalogNode[] }

/** GET /api/knowledge/topics/{topic_id} */
export type TopicResponse = {
  topic: {
    id: string
    parent_id: string | null
    name: string
    kind: string
    definition: string
    conditions: string[]
    boundaries: string[]
  }
  performance: {
    state: string
    state_reason: string
    successes: number
    failures: number
    pending: number
    attempt_count: number
    /** 按来源拆分：原卷、对口练习为表现事件数；自由练习为整题作答次数 */
    source_counts?: { exam: number; practice: number; free_practice: FreePracticeCounts }
  }
  question_counts: { completed: number; bank: number }
  /** 各题集的关联题数；稀疏，不能相加当总数 */
  collection_counts: { collection_id: string; bank: number; ready: number; completed: number }[]
  practice_counts: PracticeCounts
}
