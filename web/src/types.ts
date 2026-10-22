export type View = 'paper' | 'papers' | 'bank' | 'profile' | 'settings'

export type VisibleContext = {
  view: string; label: string; paper_id?: string; question_id?: string;
  section?: string; probe_id?: string; bank_id?: string; expanded?: string[]
}

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
  math_type: number; year: string; number: number; can_view: boolean; reserved: boolean; reason: string; analysis_allowed: boolean;
  stem?: string; tags?: string[]; question_image?: string; analysis_image?: string
  fingerprint?: { objects?: string[]; method?: string[]; stages?: string[] }
}

export type Profile = {
  stages: Record<string, { state: string; evidence: number; failures: number; successes: number }>
  repeated_errors: Array<{ label: string; count: number }>
}

export type Preferences = {study_type:number;reserved:{math_type:number;year:string}[]}
export type Bootstrap = { papers: Paper[]; questions: Question[]; bank: BankQuestion[]; profile: Profile; loop: import('./LearningWorkspace').Loop; preferences:Preferences }
