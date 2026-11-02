/**
 * 本地演示数据，内容与静态样稿一致。接口就绪后 src/api/endpoints.ts 改为真实请求，
 * 这里只留给测试和离线预览使用。
 */
import type {
  BackgroundStatus,
  HomeData,
  PaperDetail,
  PracticeDetail,
  PracticeOverview,
  QuestionAnalysis,
  QuestionSummary,
} from '../api/types'

const r = String.raw

export const paper2023 = { id: 'paper-2023-1', title: '2023 数学一' }
const paper2026 = { id: 'paper-2026-1', title: '2026 数学一' }

export const backgroundStatus: BackgroundStatus = {
  assistant: 'ready',
  running: { id: 'task-1', label: '正在分析《2023 数学一》' },
  queued: [{ id: 'task-2', label: '批改「二重积分交换积分次序」第 1 道' }],
  failed: [],
}

export const home: HomeData = {
  stats: { weeklyPracticeDone: 8, independentAccuracy: 0.63, analyzedPapers: 3 },
  nextStep: {
    title: '确认《2023 数学一》第 7 题的作答',
    description:
      '这道题的选项涂改过，做题龙看不清你最后选的是 B 还是 D。确认之后，这份试卷的练习就会自动生成。',
    actionLabel: '去确认',
    to: `/papers/${paper2023.id}/questions/7`,
    preview: { caption: '原卷第 2 页 · 第 7 题' },
  },
  todos: {
    review: [
      { paper: paper2023, questionNumber: '7', reason: '选项涂改，看不清最后的选择' },
      { paper: paper2023, questionNumber: '19', reason: '红笔批改盖住了第二步作答' },
    ],
    practice: [
      {
        topicId: 'topic-equiv-sum',
        topicName: '加减运算中的等价无穷小替换',
        origin: { paper: paper2023, questionNumber: '17' },
        remaining: 2,
      },
      {
        topicId: 'topic-double-integral-order',
        topicName: '二重积分交换积分次序',
        origin: { paper: paper2023, questionNumber: '18' },
        remaining: 2,
      },
      {
        topicId: 'topic-matrix-rank',
        topicName: '矩阵的秩',
        origin: { paper: paper2026, questionNumber: '6' },
        remaining: 1,
      },
    ],
    grading: [
      { practiceId: 'pr-4', label: '二重积分交换积分次序 · 第 1 道', submittedMinutesAgo: 3 },
    ],
    feedback: [
      {
        practiceId: 'pr-1',
        label: '加减运算中的等价无穷小替换 · 第 1 道',
        summary: '思路对，最后一步系数算错',
        outcome: 'partial',
      },
      {
        practiceId: 'pr-8',
        label: '定积分的换元法 · 第 2 道',
        summary: '换元后上下限处理正确',
        outcome: 'correct',
      },
    ],
  },
  suggestions: [
    {
      id: 's-1',
      kind: 'repeated_errors',
      title: '「矩阵的秩」最近 3 次都没做对',
      detail: '两份试卷和一道练习都在这个考点失分。建议先回看定义和常用结论，再做练习。',
      actionLabel: '查看考点',
      to: '/topics/topic-matrix-rank',
    },
    {
      id: 's-2',
      kind: 'no_practice',
      title: '《2026 数学一》已完成逐题分析',
      detail: '发现 4 个需要加强的考点，还没有生成对应练习。',
      actionLabel: '生成练习',
      to: `/papers/${paper2026.id}`,
    },
    {
      id: 's-3',
      kind: 'unfinished_practice',
      title: '「二重积分交换积分次序」还有 2 道没做',
      detail: '上周已经出错两次，趁记忆还新把剩下的做完。',
      actionLabel: '去练习',
      to: '/practice?item=pr-5',
    },
  ],
}

const paper2023Questions: [string, QuestionSummary['section'], QuestionSummary['status']][] = [
  ['1', 'choice', 'correct'],
  ['2', 'choice', 'correct'],
  ['3', 'choice', 'wrong'],
  ['4', 'choice', 'correct'],
  ['5', 'choice', 'correct'],
  ['6', 'choice', 'correct'],
  ['7', 'choice', 'unknown'],
  ['8', 'choice', 'correct'],
  ['9', 'choice', 'correct'],
  ['10', 'choice', 'wrong'],
  ['11', 'fill', 'correct'],
  ['12', 'fill', 'analyzing'],
  ['13', 'fill', 'correct'],
  ['14', 'fill', 'wrong'],
  ['15', 'fill', 'correct'],
  ['16', 'fill', 'correct'],
  ['17', 'solution', 'wrong'],
  ['18', 'solution', 'partial'],
  ['19', 'solution', 'unknown'],
  ['20', 'solution', 'correct'],
  ['21', 'solution', 'partial'],
  ['22', 'solution', 'wrong'],
]

export const papers: PaperDetail[] = [
  {
    ...paper2023,
    examDate: '2026-10-28',
    score: 96,
    totalScore: 150,
    questions: paper2023Questions.map(([number, section, status]) => ({ number, section, status })),
  },
  {
    // 演示无法匹配题库时只按题号排列
    ...paper2026,
    examDate: '2026-10-21',
    score: 104,
    totalScore: 150,
    questions: Array.from({ length: 22 }, (_, i) => ({
      number: String(i + 1),
      section: null,
      status: i % 5 === 2 ? 'wrong' : 'correct',
    })),
  },
]

export const analyses: QuestionAnalysis[] = [
  {
    paperId: paper2023.id,
    number: '17',
    section: 'solution',
    outcome: 'wrong',
    score: 2,
    maxScore: 10,
    conclusion: '思路方向对，但在加减运算里用了等价无穷小替换，分子被算成了二阶。',
    stem: r`求极限 $\displaystyle\lim_{x\to 0}\frac{e^{x}-1-x-\frac{x^{2}}{2}}{x-\sin x}$．`,
    source: { page: 4 },
    comparison: {
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
    solution: {
      entryPoint: r`分母是三阶无穷小，所以分子也要展开到 $x^{3}$ 才能比较。看到“多项相减”就优先考虑泰勒展开。`,
      keySteps: [
        r`确定分母阶数：$x-\sin x=\frac{x^{3}}{6}+o(x^{3})$`,
        r`把 $e^{x}$ 展开到同阶，前三项正好与 $-1-x-\frac{x^{2}}{2}$ 抵消`,
        r`比较最低阶系数：$\frac{1/6}{1/6}=1$`,
      ],
    },
    causes: [
      {
        title: '把“等价替换”当成了通用规则',
        detail: '第 1 步分母处理正确，说明熟悉常见等价式，但没有区分乘除和加减两种场合。',
      },
      {
        title: '没有先判断分母阶数',
        detail: '如果先确定分母是三阶，分子算出二阶时就会发现不对劲。',
      },
    ],
    derivation: r`$$\lim_{x\to0}\frac{e^{x}-1-x-\frac{x^{2}}{2}}{x-\sin x}=\lim_{x\to0}\frac{\frac{x^{3}}{6}+o(x^{3})}{\frac{x^{3}}{6}+o(x^{3})}=1$$`,
    structure: r`已知：$x\to0$ 时的 $\frac{0}{0}$ 型极限；目标：求极限值；方法：泰勒公式、无穷小阶的比较。`,
    topics: [
      { id: 'topic-equiv-sum', name: '加减运算中的等价无穷小替换' },
      { id: 'topic-taylor-limit', name: '泰勒公式求极限' },
    ],
    practiceCount: 3,
  },
]

export const practiceOverview: PracticeOverview = {
  counts: { todo: 5, grading: 1, doneThisWeek: 8 },
  groups: [
    {
      topicId: 'topic-equiv-sum',
      topicName: '加减运算中的等价无穷小替换',
      origin: { paper: paper2023, questionNumber: '17' },
      items: [
        {
          id: 'pr-1',
          order: 1,
          source: { mathType: 1, year: 2018, number: 15 },
          status: 'graded',
          outcome: 'partial',
        },
        { id: 'pr-2', order: 2, source: { mathType: 1, year: 2021, number: 15 }, status: 'todo' },
        { id: 'pr-3', order: 3, source: { mathType: 2, year: 2016, number: 15 }, status: 'todo' },
      ],
    },
    {
      topicId: 'topic-double-integral-order',
      topicName: '二重积分交换积分次序',
      origin: { paper: paper2023, questionNumber: '18' },
      items: [
        {
          id: 'pr-4',
          order: 1,
          source: { mathType: 2, year: 2020, number: 17 },
          status: 'grading',
        },
        { id: 'pr-5', order: 2, source: { mathType: 1, year: 2019, number: 17 }, status: 'todo' },
      ],
    },
    {
      topicId: 'topic-matrix-rank',
      topicName: '矩阵的秩',
      origin: { paper: paper2026, questionNumber: '6' },
      items: [
        { id: 'pr-6', order: 1, source: { mathType: 3, year: 2022, number: 6 }, status: 'todo' },
      ],
    },
    {
      topicId: 'topic-definite-substitution',
      topicName: '定积分的换元法',
      origin: { paper: paper2026, questionNumber: '16' },
      items: [
        {
          id: 'pr-7',
          order: 1,
          source: { mathType: 2, year: 2017, number: 11 },
          status: 'graded',
          outcome: 'correct',
        },
        {
          id: 'pr-8',
          order: 2,
          source: { mathType: 3, year: 2019, number: 12 },
          status: 'graded',
          outcome: 'correct',
        },
      ],
    },
  ],
}

const equivSum = practiceOverview.groups[0]

export const practiceDetails: PracticeDetail[] = [
  {
    ...equivSum.items[0],
    topicName: equivSum.topicName,
    total: equivSum.items.length,
    kind: '解答题',
    points: 10,
    reason: r`你在《2023 数学一》第 17 题把 $e^x-1\sim x$ 用在了加减运算里。这道题检验同一个判断。`,
    masked: false,
    stem: r`求极限 $\displaystyle\lim_{x\to 0}\frac{\tan x-\sin x}{x^{3}}$．`,
    attempt: {
      text: r`原式 $=\lim\frac{\tan x(1-\cos x)}{x^{3}}=\lim\frac{x\cdot\frac{x^{2}}{2}}{x^{3}}=\frac{1}{3}$`,
      photoCount: 1,
      gradedAt: '今天 14:20',
    },
    feedback: {
      outcome: 'partial',
      headline: '思路对了，最后一步算错了系数',
      correctParts: [
        r`先提出 $\tan x$，把相减变成相乘，再用等价替换——这正是本考点要练的。`,
        r`$1-\cos x\sim\frac{x^{2}}{2}$ 用得正确。`,
      ],
      firstError: r`最后一步 $\frac{x\cdot\frac{x^{2}}{2}}{x^{3}}$ 应等于 $\frac{1}{2}$，写成了 $\frac{1}{3}$。属于计算失误，方法没有问题。`,
      nextStep: {
        text: '这个考点的方法已经掌握，继续做第 2 道巩固。',
        actionLabel: '去做第 2 道',
        practiceId: 'pr-2',
      },
      derivation: r`$$\lim_{x\to0}\frac{\tan x-\sin x}{x^{3}}=\lim_{x\to0}\frac{\tan x\,(1-\cos x)}{x^{3}}=\lim_{x\to0}\frac{x\cdot\frac{x^{2}}{2}}{x^{3}}=\frac12$$`,
    },
  },
  {
    ...equivSum.items[1],
    topicName: equivSum.topicName,
    total: equivSum.items.length,
    kind: '解答题',
    points: 10,
    reason: r`你在《2023 数学一》第 17 题把 $e^x-1\sim x$ 用在了加减运算里。这道题同样需要判断能否整体替换。`,
    masked: true,
    stem: r`设 $\displaystyle\lim_{x\to0}\frac{\ln(1+x)-x+ax^{2}}{x^{2}\tan x}=b$，求常数 $a,b$ 的值，并说明理由。`,
    attempt: null,
    feedback: null,
  },
]
