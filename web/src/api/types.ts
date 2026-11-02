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
  math_type: MathType
  year: string
  number: number
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

/* ---------- 首页（契约未覆盖：首页规则留到后续批次） ---------- */

export type HomeData = {
  stats: { weekly_practice_done: number; independent_accuracy: number; analyzed_papers: number }
  next_step: {
    title: string
    description: string
    action_label: string
    to: string
    preview_caption?: string
  } | null
  todos: {
    review: { paper_id: string; paper_title: string; question_number: string; reason: string }[]
    practice: {
      topic: TopicRef
      paper_title: string
      question_number: string
      remaining: number
      practice_id: string
    }[]
    grading: { practice_id: string; label: string; submitted_at: string }[]
    feedback: { practice_id: string; label: string; summary: string; correct: boolean | null }[]
  }
  suggestions: {
    id: string
    kind: 'repeated_errors' | 'no_practice' | 'unfinished_practice'
    title: string
    detail: string
    action_label: string
    to: string
  }[]
}
