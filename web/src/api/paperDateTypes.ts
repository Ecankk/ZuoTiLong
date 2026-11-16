/* ---------- 作答日期、重复上传（B28，docs/frontend-api.md「作答日期、重复上传与画像修正」） ---------- */

export type ExamDatePrecision = 'day' | 'month' | 'unknown'
export type ExamDateUnknownReason = 'not_provided' | 'forgotten'
export type ImportDecision = 'accepted' | 'pending_duplicate' | 'withdrawn'

/** 作答日期三件套：day 为 YYYY-MM-DD，month 为 YYYY-MM，unknown 时为 null */
export type ExamDateFields = {
  exam_date: string | null
  exam_date_precision?: ExamDatePrecision | null
  exam_date_unknown_reason?: ExamDateUnknownReason | null
}

export type DuplicateCheck = {
  status: 'clear' | 'same_pdf' | 'same_exam_identity' | 'unresolved'
  identity: { exam_year: number; math_type: 1 | 2 | 3 } | null
  reason: string | null
  matches: {
    paper_id: string
    title: string
    exam_date: string | null
    exam_date_precision: ExamDatePrecision
    archived: boolean
    has_report: boolean
  }[]
}

/** POST /api/papers/dates（1–50 张，整批原子写） */
export type PaperDatesRequest = {
  confirmed: true
  request_id: string
  paper_ids: string[]
  exam_date: string | null
  exam_date_precision: ExamDatePrecision
  exam_date_unknown_reason: ExamDateUnknownReason | null
}

export type PaperDatesResponse = {
  updated: {
    paper_id: string
    exam_date: string | null
    exam_date_precision: ExamDatePrecision
    exam_date_unknown_reason: ExamDateUnknownReason | null
  }[]
  reused: boolean
}

/** POST /api/papers/{id}/import-decision */
export type ImportDecisionRequest = {
  confirmed: true
  request_id: string
  decision: 'retake' | 'withdraw'
  decision_revision: string
}

export type ImportDecisionResponse = {
  paper_id: string
  import_decision: 'accepted' | 'withdrawn'
  reused: boolean
}

/** 原卷失分不可用的原因 */
export type LossUnavailableReason =
  'missing_score' | 'invalid_score' | 'score_conflict' | 'not_exam'

/** 错题出处新增的日期与分数字段（weak_spots.evidence、recent_mistakes） */
export type EvidenceDateAndLoss = {
  exam_date?: string | null
  exam_date_precision?: ExamDatePrecision | null
  exam_date_unknown_reason?: ExamDateUnknownReason | null
  score_earned?: number | null
  max_score?: number | null
  lost_points?: number | null
  loss_basis?: 'saved_estimate' | null
  loss_unavailable_reason?: LossUnavailableReason | null
}
