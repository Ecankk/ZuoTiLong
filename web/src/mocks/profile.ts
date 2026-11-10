/* 画像（B26）mock：字段严格按 docs/frontend-api.md「画像与按画像选题」和 B26 契约，供测试与截图 */
import type {
  ActivityCounts,
  AtomsResponse,
  Distribution,
  Overview,
  ProfileBatch,
  ProfileNode,
  ProfileSubject,
  Trends,
} from '../api/types'

const dist = (
  mastered: number,
  learning: number,
  weak: number,
  no_record: number,
): Distribution => ({
  mastered,
  learning,
  weak,
  no_record,
})

const node = (
  id: string,
  parent_id: string | null,
  name: string,
  kind: ProfileNode['kind'],
  distribution: Distribution,
  extra: Partial<ProfileNode> = {},
): ProfileNode => {
  const observed = distribution.mastered + distribution.learning + distribution.weak
  const display_state: ProfileNode['display_state'] =
    distribution.weak > 0
      ? 'weak'
      : observed === 0
        ? 'no_record'
        : distribution.learning > 0
          ? 'learning'
          : 'mastered'
  const state: ProfileNode['state'] =
    display_state === 'weak'
      ? '需要关注'
      : display_state === 'learning'
        ? '巩固中'
        : display_state === 'mastered'
          ? '初步掌握'
          : '未覆盖'
  return {
    id,
    parent_id,
    name,
    kind,
    math_types: [1],
    state,
    state_reason: display_state === 'no_record' ? '还没有相关作答记录' : '按已有作答记录判断',
    display_state,
    distribution,
    successes: distribution.mastered * 2 + distribution.learning,
    failures: distribution.weak * 2,
    assisted: 0,
    pending: 0,
    last_attempt_at: observed ? '2026-11-08T10:00:00+08:00' : null,
    ready_question_count: 40,
    study_ready_question_count: 32,
    selectable_question_count: 20,
    ...extra,
  }
}

const chapter = (id: string, subject: string, name: string, d: Distribution) =>
  node(id, subject, name, 'chapter', d) as ProfileNode & { kind: 'chapter' }

const subject = (
  id: string,
  name: string,
  chapters: (ProfileNode & { kind: 'chapter' })[],
): ProfileSubject => {
  const total = chapters.reduce(
    (sum, c) =>
      dist(
        sum.mastered + c.distribution.mastered,
        sum.learning + c.distribution.learning,
        sum.weak + c.distribution.weak,
        sum.no_record + c.distribution.no_record,
      ),
    dist(0, 0, 0, 0),
  )
  return { ...node(id, null, name, 'subject', total), kind: 'subject', chapters }
}

export const profileSubjects: ProfileSubject[] = [
  subject('calc', '高等数学', [
    chapter('calc-limit', 'calc', '函数、极限与连续', dist(6, 4, 2, 34)),
    chapter('calc-diff', 'calc', '一元函数微分学', dist(5, 6, 3, 38)),
    chapter('calc-int', 'calc', '一元函数积分学', dist(4, 3, 1, 41)),
    chapter('calc-multi', 'calc', '多元函数微分学', dist(2, 2, 2, 32)),
    chapter('calc-double', 'calc', '重积分', dist(1, 2, 2, 25)),
    chapter('calc-series', 'calc', '无穷级数', dist(0, 0, 0, 36)),
  ]),
  subject('linalg', '线性代数', [
    chapter('la-det', 'linalg', '行列式', dist(5, 2, 0, 9)),
    chapter('la-matrix', 'linalg', '矩阵', dist(4, 3, 1, 22)),
    chapter('la-eigen', 'linalg', '特征值与特征向量', dist(1, 2, 3, 20)),
  ]),
  subject('prob', '概率论与数理统计', [
    chapter('prob-event', 'prob', '随机事件与概率', dist(3, 2, 0, 17)),
    chapter('prob-moment', 'prob', '随机变量的数字特征', dist(2, 1, 3, 14)),
    chapter('prob-stat', 'prob', '数理统计', dist(0, 0, 0, 24)),
  ]),
]

const total = profileSubjects.reduce(
  (sum, s) =>
    dist(
      sum.mastered + s.distribution.mastered,
      sum.learning + s.distribution.learning,
      sum.weak + s.distribution.weak,
      sum.no_record + s.distribution.no_record,
    ),
  dist(0, 0, 0, 0),
)

const window = { from: '2026-10-13T00:00:00+08:00', to: '2026-11-10T00:00:00+08:00' }

export const overview: Overview = {
  generated_at: '2026-11-10T20:00:00+08:00',
  study_type: 1,
  timezone: '+08:00',
  week: { from: '2026-11-10', to: '2026-11-16', week_starts_on: 'monday' },
  catalog_release_id: 'catalog-r1',
  include_free_practice: true,
  home_stats: { attempts_this_week: 23, independent_correct_this_week: 11, grading_count: 2 },
  totals: { pending_analysis_paper_count: 1, unfinished_practice_count: 6 },
  distribution: total,
  subjects: profileSubjects,
  weak_spots: [
    {
      node_id: 'prob-moment',
      name: '随机变量的数字特征',
      kind: 'chapter',
      subject_id: 'prob',
      weak_atom_count: 3,
      observed_atom_count: 6,
      total_atom_count: 20,
      recent_failures: 4,
      recent_judged: 6,
      failure_ratio: 0.67,
      window,
      basis: '例：《2021数学一》第9题、练习“方差及其计算式”第2道；已记录首错：计算。',
      evidence: [
        {
          source: 'exam',
          paper_id: 'paper-2021',
          question_id: 'paper-2021-q9',
          practice_id: null,
          attempt_id: null,
          bank_id: null,
          label: '《2021数学一》第9题',
          question_number: '9',
          occurred_at: '2026-11-02T00:00:00+08:00',
          first_error_stage: 'calculation',
          first_error_evidence: '把 E(X²) 算成 1/λ²，漏了系数 2',
        },
        {
          source: 'practice',
          paper_id: null,
          question_id: null,
          practice_id: 'probe-var-2',
          attempt_id: 'attempt-var-2',
          bank_id: 'bank-var-2',
          label: '练习“方差及其计算式”第2道',
          occurred_at: '2026-11-06T21:00:00+08:00',
          first_error_stage: 'calculation',
          first_error_evidence: null,
        },
      ],
    },
    {
      node_id: 'la-eigen',
      name: '特征值与特征向量',
      kind: 'chapter',
      subject_id: 'linalg',
      weak_atom_count: 3,
      observed_atom_count: 6,
      total_atom_count: 26,
      recent_failures: 3,
      recent_judged: 5,
      failure_ratio: 0.6,
      window,
      basis: '例：《2021数学一》第21题；已记录首错：建模。',
      evidence: [
        {
          source: 'exam',
          paper_id: 'paper-2021',
          question_id: 'paper-2021-q21',
          practice_id: null,
          attempt_id: null,
          bank_id: null,
          label: '《2021数学一》第21题',
          occurred_at: '2026-11-02T00:00:00+08:00',
          first_error_stage: 'modeling',
          first_error_evidence: '没有用到实对称矩阵可正交对角化',
        },
      ],
    },
    {
      node_id: 'calc-double',
      name: '重积分',
      kind: 'chapter',
      subject_id: 'calc',
      weak_atom_count: 2,
      observed_atom_count: 5,
      total_atom_count: 30,
      recent_failures: 2,
      recent_judged: 4,
      failure_ratio: 0.5,
      window,
      basis: null,
      evidence: [],
    },
  ],
  conclusions: {
    strongest_chapter: {
      node_id: 'la-det',
      name: '行列式',
      subject_id: 'linalg',
      basis: '就已有记录而言：做了 6 道，对 5 道，覆盖 7 个考点，没有要补的考点。',
      judged_count: 6,
      successes: 5,
      failures: 1,
      independent_correct: 4,
      observed_atom_count: 7,
      total_atom_count: 16,
      weak_atom_count: 0,
      last_attempt_at: '2026-11-07T20:00:00+08:00',
    },
    weakest_chapter: {
      node_id: 'prob-moment',
      name: '随机变量的数字特征',
      subject_id: 'prob',
      basis: '就已有记录而言：近 28 天做了 6 道，错 4 道，3 个考点要补。',
      judged_count: 6,
      successes: 2,
      failures: 4,
      independent_correct: 1,
      observed_atom_count: 6,
      total_atom_count: 20,
      weak_atom_count: 3,
      last_attempt_at: '2026-11-06T21:00:00+08:00',
    },
    independent_correct_comparison: {
      previous: {
        from: '2026-09-15',
        to: '2026-10-13',
        independent_correct: 14,
        independent_judged: 30,
      },
      current: {
        from: '2026-10-13',
        to: '2026-11-10',
        independent_correct: 26,
        independent_judged: 41,
      },
      delta: 12,
      basis:
        '近 4 个完整周独立做对 26 次，前 4 周 14 次（相差 12 次）；练习数量和覆盖不同也会影响这个数。',
    },
    unavailable_reasons: {
      strongest_chapter: null,
      weakest_chapter: null,
      independent_correct_comparison: null,
    },
  },
  recent_mistakes: [],
  next_steps: [
    {
      kind: 'continue_practice',
      available: true,
      reason: '还有 6 道练习没做完',
      count: 6,
      target: { paper_id: null, practice_id: 'probe-var-3' },
    },
    {
      kind: 'analyze_paper',
      available: true,
      reason: '《2024数学一》已切好题，等你核对题号',
      count: 1,
      target: { paper_id: 'paper-2024', practice_id: null },
    },
    {
      kind: 'profile_batch',
      available: true,
      reason: '有 9 个考点可以按画像挑题',
      count: 9,
      target: { paper_id: null, practice_id: null },
    },
  ],
  profile_batch_eligibility: {
    can_create: true,
    reason: null,
    target_counts: { weak: 4, review_due: 3, uncovered: 2 },
  },
  limitations: ['原卷的作答日期按导入时间计算。'],
}

/** 有少量记录、但不够下结论：没有薄弱排行，三张卡都为 null */
export const insufficientOverview: Overview = {
  ...overview,
  home_stats: { attempts_this_week: 2, independent_correct_this_week: 1, grading_count: 0 },
  weak_spots: [],
  conclusions: {
    strongest_chapter: null,
    weakest_chapter: null,
    independent_correct_comparison: null,
    unavailable_reasons: {
      strongest_chapter: '还没有哪一章在 2 天以上做过至少 5 道题。',
      weakest_chapter: '近 28 天还没有哪一章错了 2 次以上。',
      independent_correct_comparison: '最近 8 周里有一段时间没有可比较的独立作答记录。',
    },
  },
  next_steps: [
    {
      ...overview.next_steps[0],
      available: false,
      count: 0,
      reason: '没有未做完的练习',
      target: { paper_id: null, practice_id: null },
    },
    {
      ...overview.next_steps[1],
      available: false,
      count: 0,
      reason: '没有等你核对的新试卷',
      target: { paper_id: null, practice_id: null },
    },
    overview.next_steps[2],
  ],
}

const emptyDist = (n: number) => dist(0, 0, 0, n)

/** 新工作区：没有任何记录，也没选备考类别 */
export const emptyOverview: Overview = {
  ...overview,
  study_type: null,
  home_stats: { attempts_this_week: 0, independent_correct_this_week: 0, grading_count: 0 },
  totals: { pending_analysis_paper_count: 0, unfinished_practice_count: 0 },
  distribution: emptyDist(total.mastered + total.learning + total.weak + total.no_record),
  subjects: profileSubjects.map((s) => ({
    ...s,
    ...node(
      s.id,
      null,
      s.name,
      'subject',
      emptyDist(
        s.chapters.reduce(
          (n, c) =>
            n +
            c.distribution.mastered +
            c.distribution.learning +
            c.distribution.weak +
            c.distribution.no_record,
          0,
        ),
      ),
    ),
    kind: 'subject',
    chapters: s.chapters.map((c) =>
      chapter(
        c.id,
        s.id,
        c.name,
        emptyDist(
          c.distribution.mastered +
            c.distribution.learning +
            c.distribution.weak +
            c.distribution.no_record,
        ),
      ),
    ),
  })),
  weak_spots: [],
  conclusions: {
    strongest_chapter: null,
    weakest_chapter: null,
    independent_correct_comparison: null,
    unavailable_reasons: {
      strongest_chapter: '还没有作答记录。',
      weakest_chapter: '还没有作答记录。',
      independent_correct_comparison: '还没有作答记录。',
    },
  },
  next_steps: [
    {
      kind: 'continue_practice',
      available: false,
      reason: '没有未做完的练习',
      count: 0,
      target: { paper_id: null, practice_id: null },
    },
    {
      kind: 'analyze_paper',
      available: false,
      reason: '没有等你核对的新试卷',
      count: 0,
      target: { paper_id: null, practice_id: null },
    },
    {
      kind: 'profile_batch',
      available: false,
      reason: '先在设置里选择备考类别',
      count: 0,
      target: { paper_id: null, practice_id: null },
    },
  ],
  profile_batch_eligibility: {
    can_create: false,
    reason: '先在设置里选择备考类别，做题龙才知道按哪类真题挑题。',
    target_counts: { weak: 0, review_due: 0, uncovered: 0 },
  },
  limitations: ['还没有作答记录，画像会在做过题后出现。'],
}

const counts = (
  independent: number,
  assisted: number,
  wrong: number,
  unknown = 0,
): ActivityCounts => ({
  attempts: independent + assisted + wrong + unknown,
  correct: independent + assisted + unknown,
  independent_correct: independent,
  assisted_correct: assisted,
  independence_unknown_correct: unknown,
  wrong,
  unjudged: 0,
  pending_grading: 0,
})

const weeks = [
  '2026-09-01',
  '2026-09-08',
  '2026-09-15',
  '2026-09-22',
  '2026-09-29',
  '2026-10-06',
  '2026-10-13',
  '2026-10-20',
  '2026-10-27',
  '2026-11-03',
  '2026-11-10',
]
const series: [number, number, number, number][] = [
  [0, 0, 0, 0],
  [2, 0, 3, 4],
  [3, 1, 4, 0],
  [4, 1, 3, 0],
  [2, 0, 2, 6],
  [5, 1, 4, 0],
  [6, 2, 3, 0],
  [7, 1, 4, 3],
  [8, 2, 3, 0],
  [9, 2, 5, 0],
  [6, 1, 2, 0],
]

export const trends: Trends = {
  generated_at: '2026-11-10T20:00:00+08:00',
  timezone: '+08:00',
  include_free_practice: true,
  period: { from: '2026-09-01', to: '2026-11-17', weeks: weeks.length, week_starts_on: 'monday' },
  weekly: weeks.map((week_start, i) => {
    const [ind, assisted, wrong, unknownExam] = series[i]
    return {
      week_start,
      week_end: week_start,
      complete: i < weeks.length - 1,
      sources: {
        exam: counts(0, 0, Math.ceil(wrong / 2), unknownExam),
        practice: counts(Math.ceil(ind * 0.7), assisted, Math.floor(wrong / 2)),
        free_practice: counts(ind - Math.ceil(ind * 0.7), 0, 0),
      },
    }
  }),
  totals: counts(52, 11, 37, 13),
  undated: counts(0, 0, 0, 0),
  limitations: ['原卷的作答日期按导入时间计算，独立性未知的原卷正确不算独立做对。'],
}

export function atomsFor(nodeId: string): AtomsResponse {
  const parent = profileSubjects.flatMap((s) => s.chapters).find((c) => c.id === nodeId)
  const d = parent?.distribution ?? dist(0, 0, 0, 12)
  const states: Distribution[] = [
    ...Array.from({ length: d.weak }, () => dist(0, 0, 1, 0)),
    ...Array.from({ length: d.learning }, () => dist(0, 1, 0, 0)),
    ...Array.from({ length: d.mastered }, () => dist(1, 0, 0, 0)),
    ...Array.from({ length: d.no_record }, () => dist(0, 0, 0, 1)),
  ]
  // 交错一下，让格子看起来像目录顺序
  const items = states.map((s, i) =>
    node(`${nodeId}-a${i + 1}`, nodeId, `${parent?.name ?? '考点'} · 考点 ${i + 1}`, 'atom', s),
  )
  const ordered = items.filter((_, i) => i % 2 === 0).concat(items.filter((_, i) => i % 2 === 1))
  return {
    node: { id: nodeId, name: parent?.name ?? nodeId, kind: 'chapter' },
    items: ordered,
    total: ordered.length,
    offset: 0,
    limit: 100,
    next_offset: null,
  }
}

export const batchBase: ProfileBatch = {
  id: 'profile-batch-1',
  source: 'profile_practice',
  title: '按画像选题 · 8 道',
  requested_size: 8,
  status: 'selecting',
  created_at: '2026-11-10T20:10:00+08:00',
  completed_at: null,
  scope: {},
  job_id: 'job-profile-1',
  result_id: null,
  actual_size: 0,
  practice_ids: [],
  targets: [],
  limitations: [],
  counts: { pending: 0, grading: 0, graded: 0, needs_supplement: 0 },
  error: null,
}

export const batchReady: ProfileBatch = {
  ...batchBase,
  status: 'ready',
  completed_at: '2026-11-10T20:14:00+08:00',
  result_id: 'result-1',
  actual_size: 7,
  practice_ids: ['profile-probe-1', 'profile-probe-2'],
  targets: [
    {
      goal_id: 'g1',
      topic_id: 'atom-var',
      name: '方差及其计算式',
      category: 'weak',
      reason: '最近一次做错',
    },
    {
      goal_id: 'g2',
      topic_id: 'atom-eig',
      name: '特征值的性质',
      category: 'review_due',
      reason: '只有看过答案后做对',
    },
  ],
  limitations: [{ goal_id: null, reason: '“数理统计”暂时没有合适的题，少发了 1 道。' }],
  counts: { pending: 7, grading: 0, graded: 0, needs_supplement: 0 },
}
