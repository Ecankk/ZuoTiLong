/* B28 mock：只用 docs/frontend-api.md「作答日期、重复上传与画像修正」里写明的字段 */
import type { ImportResult, Page, Paper, PaperResponse } from '../api/types'
import { papers } from './data'

const base = papers[0]
const counts = { correct: 0, wrong: 0, partial: 0, unknown: 0, total: 0 }

const paper = (patch: Partial<Paper> & Pick<Paper, 'id' | 'title'>): Paper => ({
  ...base.paper,
  exam_date: null,
  exam_date_precision: 'unknown',
  exam_date_unknown_reason: 'not_provided',
  import_decision: 'accepted',
  score: null,
  analysis_status: 'segmented',
  counts,
  ...patch,
})

export const datedPapers: Paper[] = [
  // 故意打乱顺序，页面按“已知日期新到旧、未知在后”排
  paper({ id: 'p-unknown', title: '2019 数学一', exam_date_unknown_reason: 'not_provided' }),
  paper({
    id: 'p-day',
    title: '2023 数学一',
    exam_date: '2026-10-18',
    exam_date_precision: 'day',
    exam_date_unknown_reason: null,
    score: 96,
    analysis_status: 'diagnosed',
  }),
  paper({ id: 'p-forgot', title: '2020 数学一', exam_date_unknown_reason: 'forgotten' }),
  paper({
    id: 'p-month',
    title: '2022 数学一',
    exam_date: '2026-10',
    exam_date_precision: 'month',
    exam_date_unknown_reason: null,
  }),
  paper({
    id: 'p-dup',
    title: '2023 数学一（重做）',
    exam_date: '2026-11',
    exam_date_precision: 'month',
    exam_date_unknown_reason: null,
    import_decision: 'pending_duplicate',
  }),
]

export const datedList: Page<Paper> = {
  items: datedPapers,
  total: datedPapers.length,
  offset: 0,
  limit: 100,
  next_offset: null,
}

export const duplicateCheck: NonNullable<ImportResult['duplicate_check']> = {
  status: 'same_exam_identity',
  identity: { exam_year: 2023, math_type: 1 },
  reason: null,
  matches: [
    {
      paper_id: 'p-day',
      title: '2023 数学一',
      exam_date: '2026-10-18',
      exam_date_precision: 'day',
      archived: false,
      has_report: true,
    },
  ],
}

export const duplicateImport: ImportResult = {
  paper: datedPapers[4],
  sha256: 'b'.repeat(64),
  reused: false,
  duplicate_check: duplicateCheck,
  import_decision: 'pending_duplicate',
  decision_revision: 'rev-1',
}

export const clearImport = (id: string): ImportResult => ({
  paper: paper({ id, title: '新卷' }),
  sha256: 'a'.repeat(64),
  reused: false,
  duplicate_check: { status: 'clear', identity: null, reason: null, matches: [] },
  import_decision: 'accepted',
  decision_revision: null,
})

/** pending_duplicate 卷的详情：不给 analyze，带当前 duplicate_check */
export const duplicateDetail: PaperResponse = {
  ...base,
  paper: datedPapers[4],
  analysis: {
    report_id: null,
    completion: null,
    review_status: null,
    summary: '',
    limitations: [],
  },
  weak_topics: [],
  actions: [],
  duplicate_check: duplicateCheck,
  decision_revision: 'rev-1',
}
