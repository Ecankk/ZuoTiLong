/**
 * 前端使用的数据形状。接口契约（docs/frontend-api.md）确定前按样稿需要定义；
 * 拿到契约后在此对齐字段，页面只依赖这里的类型。
 */

export type MathType = 1 | 2 | 3

/** 结果状态：只用于已有结论的题目和练习 */
export type Outcome = 'correct' | 'wrong' | 'partial' | 'unknown'

export type QuestionSection = 'choice' | 'fill' | 'solution'

export type PaperRef = {
  id: string
  /** 不带书名号的标题，如“2023 数学一” */
  title: string
}

export type BankSource = {
  mathType: MathType
  year: number
  number: number
}

/* ---------- 后台进度 ---------- */

/** 做题龙后台能否工作：未安装/未登录时显示引导 */
export type AssistantReadiness = 'ready' | 'not_installed' | 'not_logged_in'

export type BackgroundTask = {
  id: string
  /** 一句完整的进度描述，如“正在分析《2023 数学一》” */
  label: string
  /** 失败时的日常语言说明 */
  problem?: string
}

export type BackgroundStatus = {
  assistant: AssistantReadiness
  running: BackgroundTask | null
  queued: BackgroundTask[]
  failed: BackgroundTask[]
}

/* ---------- 首页 ---------- */

export type HomeStats = {
  weeklyPracticeDone: number
  /** 0～1 */
  independentAccuracy: number
  analyzedPapers: number
}

export type NextStep = {
  title: string
  description: string
  actionLabel: string
  to: string
  preview?: { caption: string }
}

export type ReviewTodo = { paper: PaperRef; questionNumber: string; reason: string }
export type PracticeTodo = {
  topicId: string
  topicName: string
  origin: { paper: PaperRef; questionNumber: string }
  remaining: number
}
export type GradingTodo = { practiceId: string; label: string; submittedMinutesAgo: number }
export type FeedbackTodo = { practiceId: string; label: string; summary: string; outcome: Outcome }

export type Suggestion = {
  id: string
  kind: 'repeated_errors' | 'no_practice' | 'unfinished_practice'
  title: string
  detail: string
  actionLabel: string
  to: string
}

export type HomeData = {
  stats: HomeStats
  nextStep: NextStep | null
  todos: {
    review: ReviewTodo[]
    practice: PracticeTodo[]
    grading: GradingTodo[]
    feedback: FeedbackTodo[]
  }
  suggestions: Suggestion[]
}

/* ---------- 试卷与逐题分析 ---------- */

export type QuestionStatus = Outcome | 'analyzing'

export type QuestionSummary = {
  number: string
  /** 来自匹配到的题库真题；无法匹配时为 null */
  section: QuestionSection | null
  status: QuestionStatus
}

export type PaperDetail = PaperRef & {
  examDate: string
  score: number | null
  totalScore: number
  questions: QuestionSummary[]
}

export type AnalysisStep = {
  text: string
  /** error：首个错误；fix：改正；affected：受首个错误影响 */
  mark?: 'error' | 'fix' | 'affected'
  note?: string
}

export type QuestionAnalysis = {
  paperId: string
  number: string
  section: QuestionSection | null
  outcome: Outcome
  score: number | null
  maxScore: number
  conclusion: string
  stem: string
  source: { page: number }
  comparison: { yours: AnalysisStep[]; expected: AnalysisStep[]; explanation: string } | null
  solution: { entryPoint: string; keySteps: string[] }
  causes: { title: string; detail: string }[]
  derivation: string
  structure: string
  topics: { id: string; name: string }[]
  practiceCount: number
}

/* ---------- 练习 ---------- */

export type PracticeStatus = 'todo' | 'grading' | 'graded'

export type PracticeItem = {
  id: string
  order: number
  source: BankSource
  status: PracticeStatus
  outcome?: Outcome
}

export type PracticeGroup = {
  topicId: string
  topicName: string
  origin: { paper: PaperRef; questionNumber: string }
  items: PracticeItem[]
}

export type PracticeFeedback = {
  outcome: Outcome
  headline: string
  correctParts: string[]
  firstError: string | null
  nextStep: { text: string; actionLabel: string; practiceId: string } | null
  derivation: string
}

export type PracticeDetail = PracticeItem & {
  topicName: string
  total: number
  kind: string
  points: number
  reason: string
  /** 同类别真题默认遮挡，查看后记为“看过题目” */
  masked: boolean
  stem: string
  attempt: { text: string; photoCount: number; gradedAt: string } | null
  feedback: PracticeFeedback | null
}

export type PracticeOverview = {
  counts: { todo: number; grading: number; doneThisWeek: number }
  groups: PracticeGroup[]
}
