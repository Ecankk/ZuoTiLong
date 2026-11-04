/**
 * 测试用数据：内容与静态样稿一致，形状与 docs/frontend-api.md 一致。
 * 页面已接真实接口，这里只供 src/test/server.ts 模拟本地服务。
 */
import type {
  Access,
  AgentModels,
  Correctness,
  MathType,
  Page,
  Paper,
  PaperResponse,
  PracticeCard,
  PracticeCounts,
  PracticeGroup,
  PracticeResponse,
  PracticesResponse,
  Preferences,
  QuestionResponse,
  QuestionSummary,
  TasksResponse,
} from '../api/types'

const r = String.raw
const now = '2026-11-02T14:20:00+08:00'

const paper2023 = { id: 'paper-2023-1', title: '2023 数学一' }
const paper2026 = { id: 'paper-2026-1', title: '2026 数学一' }

/* ---------- 任务摘要 ---------- */

export const tasks: TasksResponse = {
  items: [
    {
      id: 'job-1',
      kind: 'analyze_paper',
      paper_id: paper2023.id,
      paper_title: paper2023.title,
      attempt_id: null,
      status: 'running',
      progress: { message: '正在分析《2023 数学一》' },
      error: null,
      created_at: now,
      updated_at: now,
      allowed_actions: [],
    },
    {
      id: 'job-2',
      kind: 'grade_attempt',
      paper_id: paper2023.id,
      paper_title: paper2023.title,
      attempt_id: 'attempt-4',
      status: 'queued',
      progress: { message: '等待批改「二重积分交换积分次序」第 1 道' },
      error: null,
      created_at: now,
      updated_at: now,
      allowed_actions: ['cancel'],
    },
  ],
  total: 2,
  offset: 0,
  limit: 20,
  next_offset: null,
  status: 'running',
  availability: { status: 'available', reason: null, message: '' },
  active: null,
  queued_count: 1,
  failed_count: 0,
}
tasks.active = tasks.items[0]

/* ---------- 试卷与题目 ---------- */

const typeName = { c: '选择题', f: '填空题', s: '解答题' } as const
const maxScore = { c: 5, f: 5, s: 10 } as const

// 每项：题号、题型、正误、得分、是否已有分析
const spec2023: [number, keyof typeof typeName, Correctness, number | null, boolean][] = [
  [1, 'c', 'correct', 5, true],
  [2, 'c', 'correct', 5, true],
  [3, 'c', 'wrong', 0, true],
  [4, 'c', 'correct', 5, true],
  [5, 'c', 'correct', 5, true],
  [6, 'c', 'correct', 5, true],
  [7, 'c', 'unknown', null, true],
  [8, 'c', 'correct', 5, true],
  [9, 'c', 'correct', 5, true],
  [10, 'c', 'wrong', 0, true],
  [11, 'f', 'correct', 5, true],
  [12, 'f', 'unknown', null, false],
  [13, 'f', 'correct', 5, true],
  [14, 'f', 'wrong', 0, true],
  [15, 'f', 'correct', 5, true],
  [16, 'f', 'correct', 5, true],
  [17, 's', 'wrong', 2, true],
  [18, 's', 'partial', 6, true],
  [19, 's', 'unknown', null, true],
  [20, 's', 'correct', 10, true],
  [21, 's', 'partial', 7, true],
  [22, 's', 'wrong', 3, true],
]

const questionId = (paperId: string, number: number) => `${paperId}-q${number}`

export const questions: QuestionSummary[] = [
  ...spec2023.map(([number, type, correctness, score, available]) => ({
    id: questionId(paper2023.id, number),
    paper_id: paper2023.id,
    number: String(number),
    question_type: typeName[type],
    max_score: maxScore[type],
    score_earned: score,
    correctness,
    review_state: correctness === 'unknown' ? 'needs_review' : 'done',
    analysis_available: available,
    matched_bank_id: `bank-1-2023-${number}`,
  })),
  // 《2026 数学一》未匹配到题库：没有题型，题号条只按题号排列
  ...Array.from({ length: 22 }, (_, index) => ({
    id: questionId(paper2026.id, index + 1),
    paper_id: paper2026.id,
    number: String(index + 1),
    question_type: null,
    max_score: null,
    score_earned: null,
    correctness: (index % 5 === 2 ? 'wrong' : 'correct') as Correctness,
    review_state: 'done',
    analysis_available: true,
    matched_bank_id: null,
  })),
]

const counts = (paperId: string) => {
  const items = questions.filter((q) => q.paper_id === paperId)
  const of = (value: Correctness) => items.filter((q) => q.correctness === value).length
  return {
    correct: of('correct'),
    wrong: of('wrong'),
    partial: of('partial'),
    unknown: of('unknown'),
    total: items.length,
  }
}

const practiceCounts = (partial: Partial<PracticeCounts>): PracticeCounts => {
  const value = { pending: 0, grading: 0, graded: 0, needs_supplement: 0, inactive: 0, ...partial }
  return { ...value, total: Object.values(value).reduce((sum, n) => sum + n, 0) }
}

export const papers: PaperResponse[] = [
  {
    paper: {
      ...paper2023,
      exam_date: '2026-10-28',
      score: 96,
      total_score: 150,
      score_confirmed: true,
      archived_at: null,
      created_at: '2026-10-28T20:00:00+08:00',
      updated_at: now,
      analysis_status: 'partial_analysis',
      counts: counts(paper2023.id),
    },
    analysis: {
      report_id: 'report-2023-1',
      completion: 'partial',
      review_status: 'needs_review',
      summary: '',
      limitations: [],
    },
    weak_topics: [{ topic_id: 'topic-equiv-sum', name: '加减运算中的等价无穷小替换' }],
    practice_counts: practiceCounts({ pending: 3, grading: 1, graded: 1 }),
    summary_status: 'missing',
    actions: [],
  },
  {
    paper: {
      ...paper2026,
      exam_date: '2026-10-21',
      score: null,
      total_score: 150,
      score_confirmed: false,
      archived_at: null,
      created_at: '2026-10-21T20:00:00+08:00',
      updated_at: null,
      analysis_status: 'diagnosed',
      counts: counts(paper2026.id),
    },
    analysis: {
      report_id: 'report-2026-1',
      completion: 'complete',
      review_status: 'passed',
      summary: '',
      limitations: [],
    },
    weak_topics: [{ topic_id: 'topic-matrix-rank', name: '矩阵的秩' }],
    practice_counts: practiceCounts({ pending: 1, graded: 2 }),
    summary_status: 'missing',
    actions: [],
  },
]

const q17 = questions.find((q) => q.id === questionId(paper2023.id, 17))!

export const questionDetails: QuestionResponse[] = [
  {
    question: {
      ...q17,
      stem: r`求极限 $\displaystyle\lim_{x\to 0}\frac{e^{x}-1-x-\frac{x^{2}}{2}}{x-\sin x}$．`,
      regions: [{ page: 4, bbox: [56, 120, 540, 420], role: 'question_and_work' }],
    },
    diagnosis: {
      stem: r`求极限 $\displaystyle\lim_{x\to 0}\frac{e^{x}-1-x-\frac{x^{2}}{2}}{x-\sin x}$．`,
      observation: '思路方向对，但在加减运算里用了等价无穷小替换，分子被算成了二阶。',
      correctness: 'wrong',
      answer_evidence: {
        student_work: r`由 $e^{x}-1\sim x$，分子化为 $-\frac{x^{2}}{2}$，原式 $=\infty$`,
        student_state: 'visible',
        marking: 'wrong',
        marking_note: '红笔圈出第二步',
      },
      correct_parts: [r`分母 $x-\sin x\sim\frac{x^{3}}{6}$ 处理正确`],
      first_error: {
        stage: 'formula',
        step: r`由 $e^{x}-1\sim x$，分子化为 $-\frac{x^{2}}{2}$`,
        evidence: '在相减的式子里整体替换了一部分',
      },
      solution_guide: {
        entry_point: r`分母是三阶无穷小，所以分子也要展开到 $x^{3}$ 才能比较。看到“多项相减”就优先考虑泰勒展开。`,
        strategy: '用泰勒公式把分子、分母展开到同阶后比较最低阶系数。',
        key_steps: [
          r`确定分母阶数：$x-\sin x=\frac{x^{3}}{6}+o(x^{3})$`,
          r`把 $e^{x}$ 展开到同阶，前三项正好与 $-1-x-\frac{x^{2}}{2}$ 抵消`,
          r`比较最低阶系数：$\frac{1/6}{1/6}=1$`,
        ],
        pitfalls: ['等价无穷小只能在乘除中整体替换'],
      },
      reference_answer: '1',
      reference_reasoning: r`$$\lim_{x\to0}\frac{e^{x}-1-x-\frac{x^{2}}{2}}{x-\sin x}=\lim_{x\to0}\frac{\frac{x^{3}}{6}+o(x^{3})}{\frac{x^{3}}{6}+o(x^{3})}=1$$`,
      hypotheses: [
        {
          id: 'h1',
          label: '把“等价替换”当成了通用规则',
          evidence: '第 1 步分母处理正确，说明熟悉常见等价式，但没有区分乘除和加减两种场合。',
          alternative: '',
          correction: '',
        },
        {
          id: 'h2',
          label: '没有先判断分母阶数',
          evidence: '如果先确定分母是三阶，分子算出二阶时就会发现不对劲。',
          alternative: '',
          correction: '',
        },
      ],
      fingerprint: {
        conditions: r`$x\to0$ 时的 $\frac{0}{0}$ 型极限`,
        goal: '求极限值',
        methods: ['泰勒公式', '无穷小阶的比较'],
      },
    },
    topics: [
      { topic_id: 'topic-equiv-sum', name: '加减运算中的等价无穷小替换' },
      { topic_id: 'topic-taylor-limit', name: '泰勒公式求极限' },
    ],
    evidence_urls: [`/api/questions/${q17.id}/evidence?region=0`],
    practice_counts: practiceCounts({ pending: 2, graded: 1 }),
    previous_id: questionId(paper2023.id, 16),
    next_id: questionId(paper2023.id, 18),
    capabilities: { step_comparison: true },
    step_comparison: {
      yours: [
        { text: r`分母 $x-\sin x\sim\frac{x^{3}}{6}$` },
        { text: r`由 $e^{x}-1\sim x$，分子化为 $-\frac{x^{2}}{2}$`, mark: 'error' },
        { text: r`原式 $=\lim -\frac{3}{x}=\infty$`, mark: 'affected' },
      ],
      expected: [
        { text: r`分母 $x-\sin x\sim\frac{x^{3}}{6}$，这一步没问题` },
        {
          text: r`泰勒展开到三阶：$e^{x}=1+x+\frac{x^{2}}{2}+\frac{x^{3}}{6}+o(x^{3})$`,
          mark: 'fix',
        },
        { text: r`分子 $\sim\frac{x^{3}}{6}$，原式 $=1$` },
      ],
      explanation: r`$e^{x}-1\sim x$ 只能在乘除中整体替换。这里 $e^x-1$ 和后面的 $-x-\frac{x^2}{2}$ 是相减关系，替换会把需要保留的高阶项一起丢掉。`,
    },
  },
]

/* ---------- 练习 ---------- */

const access = (math_type: MathType, year: number, number: number, masked = false): Access => ({
  id: `bank-${math_type}-${year}-${number}`,
  math_type,
  year: String(year),
  number,
  reserved: false,
  can_view: !masked,
  confirmed: true,
  cross_checked: true,
  masked,
  analysis_allowed: false,
  reason: masked ? '同类别真题，默认遮挡' : '',
})

const card = (
  id: string,
  paper: { id: string; title: string },
  topic: { topic_id: string; name: string },
  status: PracticeCard['status'],
  source: Access,
): PracticeCard => ({
  id,
  paper_id: paper.id,
  paper_title: paper.title,
  question_id: `${paper.id}-origin`,
  bank_id: source.id,
  status,
  created_at: now,
  goal_ids: [],
  topics: [topic],
  access: source,
  latest_attempt_id: status === 'pending' ? null : `attempt-${id}`,
})

const equivSum = { topic_id: 'topic-equiv-sum', name: '加减运算中的等价无穷小替换' }
const doubleIntegral = { topic_id: 'topic-double-integral-order', name: '二重积分交换积分次序' }
const matrixRank = { topic_id: 'topic-matrix-rank', name: '矩阵的秩' }
const substitution = { topic_id: 'topic-definite-substitution', name: '定积分的换元法' }

const group = (
  topic: { topic_id: string; name: string },
  items: PracticeCard[],
): PracticeGroup => ({
  id: topic.topic_id,
  label: topic.name,
  counts: practiceCounts({
    pending: items.filter((i) => i.status === 'pending').length,
    grading: items.filter((i) => i.status === 'grading').length,
    graded: items.filter((i) => i.status === 'graded').length,
  }),
  items,
})

const groups: PracticeGroup[] = [
  group(equivSum, [
    card('pr-1', paper2023, equivSum, 'graded', access(1, 2018, 15)),
    card('pr-2', paper2023, equivSum, 'pending', access(1, 2021, 15, true)),
    card('pr-3', paper2023, equivSum, 'pending', access(2, 2016, 15)),
  ]),
  group(doubleIntegral, [
    card('pr-4', paper2023, doubleIntegral, 'grading', access(2, 2020, 17)),
    card('pr-5', paper2023, doubleIntegral, 'pending', access(1, 2019, 17, true)),
  ]),
  group(matrixRank, [card('pr-6', paper2026, matrixRank, 'pending', access(3, 2022, 6))]),
  group(substitution, [
    card('pr-7', paper2026, substitution, 'graded', access(2, 2017, 11)),
    card('pr-8', paper2026, substitution, 'graded', access(3, 2019, 12)),
  ]),
]

export const practices: PracticesResponse = {
  items: groups,
  total: groups.length,
  offset: 0,
  limit: 20,
  next_offset: null,
  counts: practiceCounts({ pending: 5, grading: 1, graded: 3 }),
}

const allCards = groups.flatMap((g) => g.items)
const cardById = (id: string) => allCards.find((c) => c.id === id)!

export const practiceDetails: PracticeResponse[] = [
  {
    practice: cardById('pr-1'),
    is_current: true,
    review_reason: null,
    question: {
      question_text: r`求极限 $\displaystyle\lim_{x\to 0}\frac{\tan x-\sin x}{x^{3}}$．`,
    },
    goals: [],
    selection_reason: r`你在《2023 数学一》第 17 题把 $e^x-1\sim x$ 用在了加减运算里。这道题检验同一个判断。`,
    latest_attempt: {
      id: 'attempt-pr-1',
      probe_id: 'pr-1',
      response: r`原式 $=\lim\frac{\tan x(1-\cos x)}{x^{3}}=\lim\frac{x\cdot\frac{x^{2}}{2}}{x^{3}}=\frac{1}{3}$`,
      image_ids: ['image-1'],
      image_roles: { 'image-1': 'own_work' },
      answer_exposed: false,
      elapsed_seconds: 540,
      created_at: '2026-11-02T14:05:00+08:00',
      assessment: {
        correct: false,
        feedback: '思路对了，最后一步算错了系数',
        observations: [
          {
            step: r`先提出 $\tan x$，把相减变成相乘，再用等价替换——这正是本考点要练的。`,
            stage: 'modeling',
            status: 'valid',
            evidence: '',
          },
          {
            step: r`$1-\cos x\sim\frac{x^{2}}{2}$ 用得正确。`,
            stage: 'formula',
            status: 'valid',
            evidence: '',
          },
        ],
        first_error: {
          stage: 'calculation',
          step: r`最后一步 $\frac{x\cdot\frac{x^{2}}{2}}{x^{3}}$ 应等于 $\frac{1}{2}$，写成了 $\frac{1}{3}$。`,
          evidence: '属于计算失误，方法没有问题。',
        },
        reference_reasoning: r`$$\lim_{x\to0}\frac{\tan x-\sin x}{x^{3}}=\lim_{x\to0}\frac{\tan x\,(1-\cos x)}{x^{3}}=\lim_{x\to0}\frac{x\cdot\frac{x^{2}}{2}}{x^{3}}=\frac12$$`,
        next_step: '这个考点的方法已经掌握，继续做第 2 道巩固。',
      },
    },
    actions: ['supplement', 'reveal_analysis'],
  },
  {
    practice: cardById('pr-2'),
    is_current: true,
    review_reason: null,
    question: null,
    goals: [],
    selection_reason: r`你在《2023 数学一》第 17 题把 $e^x-1\sim x$ 用在了加减运算里。这道题同样需要判断能否整体替换。`,
    latest_attempt: null,
    actions: ['submit', 'reveal_question'],
  },
]

export const paperList: Page<Paper> = {
  items: papers.map((item) => item.paper),
  total: papers.length,
  offset: 0,
  limit: 100,
  next_offset: null,
}

export const preferences: Preferences = {
  study_type: 1,
  mask_same_type: true,
  paper_marking_convention: '黑笔为考试作答，红笔为事后批改。',
  reserved: [],
  execution_profiles: {
    judgment: { model: 'gpt-6-luna', effort: 'xhigh' },
    organization: { model: 'gpt-6-luna', effort: 'high' },
  },
}

export const agentModels: AgentModels = {
  status: 'available',
  reason: null,
  message: '',
  items: [
    { id: 'gpt-6-luna', name: 'GPT-6 Luna', efforts: ['low', 'medium', 'high', 'xhigh'] },
    { id: 'gpt-6-luna-mini', name: 'GPT-6 Luna Mini', efforts: ['low', 'medium', 'high'] },
    { id: 'gpt-6-swift', name: 'GPT-6 Swift', efforts: ['minimal', 'low'] },
  ],
}

/* 刚上传、已切题、还没开始分析的试卷 */
const freshPaper = { id: 'paper-fresh', title: '2025 数学一' }
questions.push(
  ...[1, 2, 3].map((number) => ({
    id: `${freshPaper.id}-q${number}`,
    paper_id: freshPaper.id,
    number: String(number),
    question_type: null,
    max_score: null,
    score_earned: null,
    correctness: 'unknown' as Correctness,
    review_state: 'needs_review',
    analysis_available: false,
    matched_bank_id: null,
  })),
)
papers.push({
  paper: {
    ...freshPaper,
    exam_date: '2026-11-03',
    score: null,
    total_score: 150,
    score_confirmed: false,
    archived_at: null,
    created_at: now,
    updated_at: null,
    analysis_status: 'needs_review',
    counts: { correct: 0, wrong: 0, partial: 0, unknown: 3, total: 3 },
  },
  analysis: {
    report_id: null,
    completion: null,
    review_status: null,
    summary: '',
    limitations: [],
  },
  weak_topics: [],
  practice_counts: {
    pending: 0,
    grading: 0,
    graded: 0,
    needs_supplement: 0,
    inactive: 0,
    total: 0,
  },
  summary_status: 'missing',
  actions: ['analyze', 'archive'],
})
