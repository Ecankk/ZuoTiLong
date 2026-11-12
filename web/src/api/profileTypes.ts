/* ---------- 画像与按画像选题（B26，docs/frontend-api.md「画像与按画像选题」） ---------- */

export type Distribution = { mastered: number; learning: number; weak: number; no_record: number }

export type DisplayState = 'mastered' | 'learning' | 'weak' | 'no_record'

export type ProfileNode = {
  id: string
  parent_id: string | null
  name: string
  kind: 'subject' | 'chapter' | 'topic' | 'atom'
  math_types: (1 | 2 | 3)[]
  state: '初步掌握' | '巩固中' | '需要关注' | '证据不足' | '未覆盖'
  state_reason: string
  display_state: DisplayState
  distribution: Distribution
  successes: number
  failures: number
  assisted: number
  pending: number
  last_attempt_at: string | null
  ready_question_count: number
  study_ready_question_count: number
  selectable_question_count: number
  /** B28：最近一次作答的日期（只到月或未知时 last_attempt_at 为 null） */
  last_attempt_date?: DateValue | null
}

export type ProfileSubject = ProfileNode & {
  kind: 'subject'
  chapters: (ProfileNode & { kind: 'chapter' })[]
}

export type EvidenceSource = 'exam' | 'practice' | 'free_practice'

import type {
  EvidenceDateAndLoss,
  ExamDatePrecision,
  ExamDateUnknownReason,
} from './paperDateTypes'

export type WeakSpotEvidence = EvidenceDateAndLoss & {
  source: EvidenceSource
  paper_id: string | null
  question_id: string | null
  practice_id: string | null
  attempt_id: string | null
  bank_id: string | null
  label: string
  /** 原卷题号（有题号时可直达题目页） */
  question_number?: string | null
  occurred_at: string | null
  first_error_stage: string | null
  first_error_evidence: string | null
}

export type WeakSpot = {
  node_id: string
  name: string
  kind: 'chapter' | 'topic'
  subject_id: string
  weak_atom_count: number
  observed_atom_count: number
  total_atom_count: number
  recent_failures: number
  recent_judged: number
  failure_ratio: number | null
  window: { from: string; to: string }
  basis: string | null
  evidence: WeakSpotEvidence[]
  /** B28：近期依据还是历史卷补位，以及涉及的原卷失分（按已保存估分，null 为分数未知） */
  evidence_period?: 'recent' | 'historical'
  period_explanation?: string
  recent_lost_points?: number | null
  recent_loss_known_question_count?: number
  recent_loss_unknown_question_count?: number
  historical_lost_points?: number | null
  historical_loss_known_question_count?: number
  historical_loss_unknown_question_count?: number
  recent_exam_failure_count?: number
  recent_practice_failure_count?: number
  historical_failures?: number
  historical_exam_failure_count?: number
  historical_practice_failure_count?: number
  loss_attribution?: 'related_question_loss'
  loss_basis?: 'saved_estimate' | 'mixed' | null
}

export type StageKey = 'entry' | 'modeling' | 'formula' | 'calculation' | 'finalization'

/** overview.first_error_summary：满门槛才返回，否则 null（前端不自己拼结论） */
export type FirstErrorSummary = {
  period: 'recent'
  window: { from: string; to: string }
  wrong_count: number
  attributed_count: number
  unattributed_count: number
  stages: { stage: StageKey; count: number }[]
  dominant_stage: string
  dominant_count: number
  statement: string
  evidence: {
    source: string
    paper_id: string | null
    question_id: string | null
    question_number: string | null
    practice_id: string | null
    attempt_id: string | null
    first_error_stage: string
    first_error_evidence: string
    /** 后端补丁会加：出处名，如“《2021数学一》第9题” */
    label?: string | null
  }[]
}

export type DateValue = {
  value: string | null
  precision: ExamDatePrecision
  unknown_reason: ExamDateUnknownReason | null
}

export type ChapterConclusion = {
  node_id: string
  name: string
  subject_id: string
  basis: string
  judged_count: number
  successes: number
  failures: number
  independent_correct: number
  observed_atom_count: number
  total_atom_count: number
  weak_atom_count: number
  last_attempt_at: string | null
}

export type FourWeekComparison = {
  previous: { from: string; to: string; independent_correct: number; independent_judged: number }
  current: { from: string; to: string; independent_correct: number; independent_judged: number }
  delta: number
  basis: string
}

/** 实际顺序：read_feedback → review_results → continue_practice → analyze_paper → profile_batch */
export type NextStepKind =
  'read_feedback' | 'review_results' | 'continue_practice' | 'analyze_paper' | 'profile_batch'

export type FeedbackSource = 'paper_practice' | 'profile_practice' | 'free_practice'

/** overview.feedback.recent_items：最近的批改反馈和已读状态 */
export type FeedbackItem = {
  source: FeedbackSource
  attempt_id: string
  practice_id: string | null
  paper_id: string | null
  bank_id: string | null
  batch_id: string | null
  title: string
  assessed_at: string | null
  correct: boolean | null
  feedback_revision: string
  unread: boolean
  read_at: string | null
}

/** overview.review.items：判断不确定或需要补材料的记录 */
export type ReviewItem = {
  source: EvidenceSource
  question_id: string | null
  attempt_id: string | null
  practice_id: string | null
  paper_id: string | null
  bank_id: string | null
  reason: string
}

export type NextStep = {
  kind: NextStepKind
  available: boolean
  reason: string
  count: number
  target: { paper_id: string | null; practice_id: string | null }
}

/** GET /api/profile/overview */
export type Overview = {
  generated_at: string
  study_type: 1 | 2 | 3 | null
  timezone: string
  week: { from: string; to: string; week_starts_on: 'monday' }
  catalog_release_id: string | null
  include_free_practice: boolean
  home_stats: {
    attempts_this_week: number
    independent_correct_this_week: number
    grading_count: number
  }
  totals: {
    pending_analysis_paper_count: number
    unfinished_practice_count: number
    unread_feedback_count?: number
    needs_review_count?: number
  }
  feedback?: { unread_count: number; recent_items: FeedbackItem[] }
  /** B28：薄弱排行的近期/历史说明、只到月或未知日期的作答数、全局首错环节汇总 */
  weak_spots_context?: {
    recent_window: { from: string; to: string }
    recent_judged_count: number
    recent_evidence_sufficient: boolean
    uses_history_fallback: boolean
    explanation: string | null
  }
  history_counts?: { month_dated_attempts: number; unknown_dated_attempts: number }
  first_error_summary?: FirstErrorSummary | null
  review?: {
    total: number
    counts: { exam_questions: number; practice_attempts: number; free_practice_attempts: number }
    paper_issue_count: number
    items: ReviewItem[]
  }
  distribution: Distribution
  subjects: ProfileSubject[]
  weak_spots: WeakSpot[]
  conclusions: {
    strongest_chapter: ChapterConclusion | null
    weakest_chapter: ChapterConclusion | null
    independent_correct_comparison: FourWeekComparison | null
    unavailable_reasons: {
      strongest_chapter: string | null
      weakest_chapter: string | null
      independent_correct_comparison: string | null
    }
  }
  recent_mistakes: (EvidenceDateAndLoss & {
    source: EvidenceSource
    practice_source: 'paper_practice' | 'profile_practice' | null
    question_id: string | null
    question_number?: string | null
    practice_id: string | null
    attempt_id: string | null
    paper_id: string | null
    bank_id: string | null
    batch_id: string | null
    label: string
    occurred_at: string | null
    answer_exposed: boolean | null
    topic_ids: string[]
  })[]
  next_steps: NextStep[]
  profile_batch_eligibility: {
    can_create: boolean
    reason: string | null
    target_counts: { weak: number; review_due: number; uncovered: number }
  }
  limitations: string[]
}

export type ActivityCounts = {
  attempts: number
  correct: number
  independent_correct: number
  assisted_correct: number
  independence_unknown_correct: number
  wrong: number
  unjudged: number
  pending_grading: number
}

/** GET /api/profile/trends?weeks= */
export type Trends = {
  generated_at: string
  timezone: string
  include_free_practice: boolean
  period: { from: string; to: string; weeks: number; week_starts_on: 'monday' }
  weekly: {
    week_start: string
    week_end: string
    complete: boolean
    sources: { exam: ActivityCounts; practice: ActivityCounts; free_practice: ActivityCounts }
  }[]
  totals: ActivityCounts
  undated: ActivityCounts
  /** B28：日期只到月份或未知、没放进任何一周的作答 */
  unplaced_by_precision?: { month: ActivityCounts; unknown: ActivityCounts }
  limitations: string[]
}

/** GET /api/profile/nodes/{node_id}/atoms */
export type AtomsResponse = {
  node: { id: string; name: string; kind: string }
  items: ProfileNode[]
  total: number
  offset: number
  limit: number
  next_offset: number | null
}

export type ProfileBatchSize = 5 | 8 | 10

export type ProfileBatchRequest = {
  confirmed: true
  request_id: string
  size: ProfileBatchSize
  scope?: { subject?: string; chapter_topic_id?: string }
}

export type ProfileBatchStatus =
  'queued' | 'selecting' | 'ready' | 'no_candidates' | 'failed' | 'cancelled'

/** POST /api/practices/profile-batch：202 新建 / 200 同请求重放 */
export type ProfileBatchCreated = {
  batch_id: string
  source: 'profile_practice'
  requested_size: ProfileBatchSize
  status: ProfileBatchStatus
  job_id: string
  reused: boolean
}

/** GET /api/practices/profile-batches/{batch_id} */
export type ProfileBatch = {
  id: string
  source: 'profile_practice'
  title: string
  requested_size: ProfileBatchSize
  status: ProfileBatchStatus
  created_at: string
  completed_at: string | null
  scope: { subject?: string; chapter_topic_id?: string }
  job_id: string
  result_id: string | null
  actual_size: number
  practice_ids: string[]
  targets: {
    goal_id: string
    topic_id: string
    name: string
    category: 'weak' | 'review_due' | 'uncovered'
    reason: string
  }[]
  limitations: { goal_id: string | null; reason: string }[]
  counts: { pending: number; grading: number; graded: number; needs_supplement: number }
  error: string | null
}

/** POST /api/feedback/read：已读回执（不改批改结果） */
export type FeedbackReadRequest = {
  request_id: string
  source: FeedbackSource
  attempt_id: string
  feedback_revision: string
}
