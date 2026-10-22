export type View = 'home' | 'papers' | 'queue' | 'bank' | 'profile'

export type Paper = {
  id: string
  title: string
  exam_date?: string
  score?: number
  total_score?: number
  duration?: number
  source_name?: string
  import_status?: string
  page_count?: number
  analysis_engine?: string
  analysis_message?: string
  analyzed_at?: string
}

export type Question = {
  id: string
  paper_id: string
  number: string
  subject: string
  stem: string
  score_earned: number
  max_score: number
  correctness: string
  review_status: string
  error_stage?: string
  error_type?: string
  knowledge?: string
  notes?: string
  fingerprint?: { objects?: string[]; method?: string[]; stages?: string[] }
  page_start?: number
  page_end?: number
  bbox_json?: string
  ocr_confidence?: number
  match_bank_id?: string
  match_score?: number
  source_text?: string
}

export type BankQuestion = {
  id: string
  source: string
  stem: string
  difficulty: number
  tags: string[]
  fingerprint?: { objects?: string[]; method?: string[]; stages?: string[] }
}

export type Profile = {
  stages: Record<string, { state: string; evidence: number; failures: number; successes: number }>
  repeated_errors: Array<{ label: string; count: number }>
}

export type Bootstrap = { papers: Paper[]; questions: Question[]; bank: BankQuestion[]; profile: Profile; loop: import('./LearningWorkspace').Loop }
