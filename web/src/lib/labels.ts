import type { Access, Correctness, MathType } from '../api/types'

const mathTypeNames: Record<MathType, string> = { 1: '数学一', 2: '数学二', 3: '数学三' }

export const mathTypeName = (type: MathType) => mathTypeNames[type]

export const correctnessLabel: Record<Correctness, string> = {
  correct: '正确',
  wrong: '有误',
  partial: '部分正确',
  unknown: '待核对',
}

/** 批改结果只有对/错/未判定（契约未提供“部分正确”）。 */
export const assessmentCorrectness = (correct: boolean | null): Correctness =>
  correct === null ? 'unknown' : correct ? 'correct' : 'wrong'

/** 试卷标题统一加书名号：《2023 数学一》 */
export const paperName = (title: string) => `《${title}》`

/** 题库来源：“2021 数学一” */
export const sourceName = (access: Access) => `${access.year} ${mathTypeName(access.math_type)}`

/** "2026-10-28" → "10月28日" */
export function monthDay(date: string) {
  const [, month, day] = date.split('-').map(Number)
  return `${month}月${day}日`
}
