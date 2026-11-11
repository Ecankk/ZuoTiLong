import type { ExamDateFields, ExamDatePrecision, ExamDateUnknownReason } from '../api/types'

/** 作答日期在界面上的选法：不填 / 具体日期 / 约某月 / 记不清 */
export type DateMode = 'none' | 'day' | 'month' | 'forgotten'
export type DateChoice = { mode: DateMode; value: string }

export const NO_DATE: DateChoice = { mode: 'none', value: '' }

const pad = (n: number) => String(n).padStart(2, '0')

export const todayDay = (now = new Date()) =>
  `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
export const thisMonth = (now = new Date()) => todayDay(now).slice(0, 7)

/** 选了“具体日期 / 约某月”却还没填日子时不能提交 */
export const choiceIncomplete = (choice: DateChoice) =>
  (choice.mode === 'day' && !/^\d{4}-\d{2}-\d{2}$/.test(choice.value)) ||
  (choice.mode === 'month' && !/^\d{4}-\d{2}$/.test(choice.value))

/** 上传用：没选（不填）时返回 undefined，三个字段都不传 */
export function uploadDateFields(choice: DateChoice): ExamDateFields | undefined {
  if (choice.mode === 'day') return { exam_date: choice.value, exam_date_precision: 'day' }
  if (choice.mode === 'month') return { exam_date: choice.value, exam_date_precision: 'month' }
  if (choice.mode === 'forgotten')
    return {
      exam_date: null,
      exam_date_precision: 'unknown',
      exam_date_unknown_reason: 'forgotten',
    }
  return undefined
}

/** 批量修改用：三个字段都要传，“不填”即日期未知 */
export function dateUpdateFields(choice: DateChoice): {
  exam_date: string | null
  exam_date_precision: ExamDatePrecision
  exam_date_unknown_reason: ExamDateUnknownReason | null
} {
  if (choice.mode === 'day' || choice.mode === 'month')
    return {
      exam_date: choice.value,
      exam_date_precision: choice.mode,
      exam_date_unknown_reason: null,
    }
  return {
    exam_date: null,
    exam_date_precision: 'unknown',
    exam_date_unknown_reason: choice.mode === 'forgotten' ? 'forgotten' : 'not_provided',
  }
}

type DateLike = {
  exam_date?: string | null
  exam_date_precision?: ExamDatePrecision | null
  exam_date_unknown_reason?: ExamDateUnknownReason | null
}

/** 精度：旧接口没有 precision 时按值的形状推断，YYYY-MM 绝不当完整日期 */
export function precisionOf(date: DateLike): ExamDatePrecision {
  const value = date.exam_date ?? ''
  if (date.exam_date_precision === 'unknown' || !value) return 'unknown'
  if (date.exam_date_precision === 'month' || /^\d{4}-\d{2}$/.test(value)) return 'month'
  return /^\d{4}-\d{2}-\d{2}/.test(value) ? 'day' : 'unknown'
}

/** 按精度显示：2026年10月18日 / 约2026年10月 / 日期未知 / 记不清 */
export function examDateLabel(date: DateLike): string {
  const precision = precisionOf(date)
  const value = date.exam_date ?? ''
  if (precision === 'day') {
    const [y, m, d] = value.slice(0, 10).split('-').map(Number)
    return `${y}年${m}月${d}日`
  }
  if (precision === 'month') {
    const [y, m] = value.slice(0, 7).split('-').map(Number)
    return `约${y}年${m}月`
  }
  return date.exam_date_unknown_reason === 'forgotten' ? '记不清' : '日期未知'
}

/** 卡片与标题里的一句：“2026年10月18日作答”“约2026年10月作答”“作答日期未知”“作答日期记不清” */
export function examDateLine(date: DateLike): string {
  const precision = precisionOf(date)
  if (precision !== 'unknown') return `${examDateLabel(date)}作答`
  return date.exam_date_unknown_reason === 'forgotten' ? '作答日期记不清' : '作答日期未知'
}

/** 修改时回填当前值 */
export function choiceFrom(date: DateLike): DateChoice {
  const precision = precisionOf(date)
  const value = date.exam_date ?? ''
  if (precision === 'day') return { mode: 'day', value: value.slice(0, 10) }
  if (precision === 'month') return { mode: 'month', value: value.slice(0, 7) }
  return date.exam_date_unknown_reason === 'forgotten' ? { mode: 'forgotten', value: '' } : NO_DATE
}

/** 列表排序：已知日期新到旧（月份按该月计），未知日期排在后面；同级保持原顺序 */
export function sortByExamDate<T extends DateLike>(items: T[]): T[] {
  const key = (item: T) => {
    const precision = precisionOf(item)
    if (precision === 'unknown') return ''
    // 月份精度排在同月具体日期之后（“约10月”不比“10月18日”更新）
    return precision === 'month'
      ? `${item.exam_date!.slice(0, 7)}-00`
      : item.exam_date!.slice(0, 10)
  }
  return items
    .map((item, index) => ({ item, index, k: key(item) }))
    .sort((a, b) => {
      if (!a.k !== !b.k) return a.k ? -1 : 1
      if (a.k !== b.k) return a.k < b.k ? 1 : -1
      return a.index - b.index
    })
    .map(({ item }) => item)
}
