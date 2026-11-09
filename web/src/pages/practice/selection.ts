import type { PracticeGrouping } from '../../api/endpoints'
import type { Correctness, PracticeCard, PracticeGroup, TopicRef } from '../../api/types'

/**
 * 练习页地址参数（首页、题目页、题库链接到练习时统一用这几个）：
 * - view：分组方式 topic（默认）/ paper
 * - item：选中的练习
 * - topic：考点，选中这个考点下第一道未做
 * - paper：试卷，选中这份试卷来的第一道未做
 * - status：按状态筛选 todo / waiting / wrong / right
 * - source：按来源筛选 paper / profile / free
 * - inactive=1：显示已停用的练习
 */

/** 状态筛选：未做 / 待批改 / 做错 / 做对。已停用的练习不进任何一类，只在“全部”里出现。 */
export type Bucket = 'todo' | 'waiting' | 'wrong' | 'right'
export const bucketLabel: Record<Bucket, string> = {
  todo: '未做',
  waiting: '待批改',
  wrong: '做错',
  right: '做对',
}
export const buckets: Bucket[] = ['todo', 'waiting', 'wrong', 'right']

/**
 * 练习来源：原卷补强（试卷分析后挑的）、画像选题（之后按画像挑的）、自由练习。
 * 后端还没有来源字段：有 origin 时用它，没有时有试卷就算原卷补强，都没有就不显示来源。
 */
export type Origin = 'paper' | 'profile' | 'free'
export const originLabel: Record<Origin, string> = {
  paper: '原卷补强',
  profile: '画像选题',
  free: '自由练习',
}
export const origins: Origin[] = ['paper', 'profile', 'free']

const originAliases: Record<string, Origin> = {
  paper: 'paper',
  exam: 'paper',
  profile: 'profile',
  profile_batch: 'profile',
  free: 'free',
  free_practice: 'free',
}

export function practiceOrigin(card: PracticeCard): Origin | undefined {
  const raw = (card as PracticeCard & { origin?: unknown }).origin
  if (typeof raw === 'string' && originAliases[raw]) return originAliases[raw]
  return card.paper_id ? 'paper' : undefined
}

/** 已批改练习的对错：列表接口不带，需要读每道的详情；还没读到时为 undefined。 */
export type Results = Record<string, Correctness | undefined>

export function practiceBucket(card: PracticeCard, results: Results): Bucket | undefined {
  switch (card.status) {
    case 'pending':
      return card.latest_attempt_id ? 'waiting' : 'todo'
    case 'grading':
    case 'needs_supplement':
      return 'waiting'
    case 'graded': {
      const result = results[card.id]
      if (!result) return undefined
      if (result === 'correct') return 'right'
      if (result === 'unknown') return 'waiting'
      return 'wrong'
    }
    default:
      return undefined
  }
}

/** 列表里每道题的显示状态 */
export function rowState(card: PracticeCard, results: Results, current: boolean) {
  if (card.status === 'inactive') return '已停用'
  if (card.status === 'needs_supplement') return '需要补充'
  if (card.status === 'grading') return '批改中'
  const bucket = practiceBucket(card, results)
  if (bucket === 'todo') return current ? '正在做' : '未做'
  if (bucket === 'waiting') return card.status === 'graded' ? '待核对' : '待批改'
  if (bucket === 'right') return '做对'
  if (bucket === 'wrong') return results[card.id] === 'partial' ? '部分对' : '做错'
  return '已批改'
}

export type Row = { card: PracticeCard; also: TopicRef[] }
export type Section = { group: PracticeGroup; rows: Row[] }

/**
 * 左栏分组：按考点时同一道题只出现在它第一次出现的考点下，其他考点作为标签显示在这一行；
 * 去重后没有题的考点不单独列出。
 */
export function buildSections(groups: PracticeGroup[], grouping: PracticeGrouping): Section[] {
  const seen = new Set<string>()
  const sections: Section[] = []
  for (const group of groups) {
    const rows = group.items
      .filter((card) => !seen.has(card.id))
      .map((card) => ({
        card,
        also: grouping === 'topic' ? card.topics.filter((t) => t.topic_id !== group.id) : [],
      }))
    rows.forEach((row) => seen.add(row.card.id))
    if (rows.length) sections.push({ group, rows })
  }
  return sections
}

export type Filter = { status?: Bucket; source?: Origin; query?: string }

const matchesQuery = (section: Section, row: Row, query: string) => {
  const text = [
    section.group.label,
    row.card.paper_title,
    ...row.card.topics.map((topic) => topic.name),
  ].join(' ')
  return text.toLowerCase().includes(query.toLowerCase())
}

/** 按状态、来源和搜索词过滤；当前选中的题始终保留，避免筛选后右栏和左栏对不上。 */
export function filterSections(
  sections: Section[],
  filter: Filter,
  results: Results,
  keep?: string,
): Section[] {
  const query = filter.query?.trim() ?? ''
  return sections
    .map((section) => ({
      ...section,
      rows: section.rows.filter(
        (row) =>
          row.card.id === keep ||
          ((!filter.status || practiceBucket(row.card, results) === filter.status) &&
            (!filter.source || practiceOrigin(row.card) === filter.source) &&
            (!query || matchesQuery(section, row, query))),
      ),
    }))
    .filter((section) => section.rows.length > 0)
}

/** 下一道没做的题：先找列表里当前题之后的，到底了再从头找；没有就是 undefined。 */
export function nextTodo(sections: Section[], current: string | undefined, results: Results) {
  const cards = sections.flatMap((section) => section.rows.map((row) => row.card))
  const index = cards.findIndex((card) => card.id === current)
  const ordered = [...cards.slice(index + 1), ...cards.slice(0, Math.max(index, 0))]
  return ordered.find((card) => card.id !== current && practiceBucket(card, results) === 'todo')
}

/** 默认选中：地址里指定的练习 → 指定考点或试卷的第一道未做 → 全部中的第一道未做。 */
export function pickSelected(
  groups: PracticeGroup[],
  { item, topic, paper }: { item?: string | null; topic?: string | null; paper?: string | null },
) {
  const cards = groups.flatMap((group) => group.items)
  if (item && cards.some((card) => card.id === item)) return item
  let scope = cards
  if (topic) scope = groups.find((group) => group.id === topic)?.items ?? cards
  else if (paper) {
    const fromPaper = cards.filter((card) => card.paper_id === paper)
    if (fromPaper.length) scope = fromPaper
  }
  const todo = (card: PracticeCard) => card.status === 'pending' && !card.latest_attempt_id
  return (scope.find(todo) ?? scope[0] ?? cards.find(todo) ?? cards[0])?.id
}

/* ---------- 题面里的占位文字 ---------- */

/**
 * 旧图片题的题干文字只是“2022 数学三 第22题 · 参数估计”这样的说明。
 * 有原题图时不当题干显示，把“参数估计”这样的章节拿出来当副标题。
 */
const navigationText = /^\s*\d{4}\s*数学[一二三]\s*第\s*\d+\s*题\s*(?:[·・•]\s*(.+?))?\s*$/

export function splitQuestionText(question: {
  question_text?: string | null
  question_image?: string | null
}): { text: string | null; chapter: string | null } {
  const text = question.question_text?.trim() || null
  if (!text || !question.question_image) return { text, chapter: null }
  const match = text.match(navigationText)
  return match ? { text: null, chapter: match[1]?.trim() || null } : { text, chapter: null }
}

/** “参考解析见原图”这类导航占位：后端改好之前前端先不显示（解析图仍然显示）。 */
const placeholderAnalysis = /^\s*(参考)?(解析|答案)(见|详见)(原图|图片|下图)[。.]?\s*$/

export const usefulAnalysis = (text: string | null | undefined) =>
  text && !placeholderAnalysis.test(text) ? text : null
