import type { Access, Correctness, MathType } from '../api/types'

const mathTypeNames: Record<MathType, string> = { 1: '数学一', 2: '数学二', 3: '数学三' }

export const mathTypeName = (type: MathType) => mathTypeNames[type]

export const correctnessLabel: Record<Correctness, string> = {
  correct: '正确',
  wrong: '有误',
  partial: '部分正确',
  unknown: '待核对',
}

const correctnessValues: Correctness[] = ['correct', 'wrong', 'partial', 'unknown']

/**
 * 批改结果：已保存的 answer_status 是四种结果之一时用它（含“部分正确”），
 * 否则只按 correct 区分对/错/未判定。
 */
export function assessmentCorrectness(assessment: {
  correct: boolean | null
  answer_status?: string
}): Correctness {
  const status = assessment.answer_status as Correctness | undefined
  if (status && correctnessValues.includes(status)) return status
  return assessment.correct === null ? 'unknown' : assessment.correct ? 'correct' : 'wrong'
}

/** 试卷标题统一加书名号：《2023 数学一》 */
export const paperName = (title: string) => `《${title}》`

/** 题库来源：“2021 数学一”；题集题没有年份或类别时返回空字符串 */
export const sourceName = (access: Access) =>
  access.year && access.math_type ? `${access.year} ${mathTypeName(access.math_type)}` : ''

/** 练习题出处：“2021 数学一 · 第 3 题”；缺的部分不显示，全缺时为空字符串 */
export function practiceSource(access: Access) {
  const exam = sourceName(access)
  if (exam) return [exam, access.number ? `第 ${access.number} 题` : ''].filter(Boolean).join(' · ')
  // 题集题（如张宇1000题）：题集名 · 章 · 原题号；缺的部分不显示
  const number = access.book?.number?.trim()
  return [
    access.collection_label,
    access.book?.chapter,
    number
      ? /^\d+$/.test(number)
        ? `第 ${number} 题`
        : number
      : access.number
        ? `第 ${access.number} 题`
        : '',
  ]
    .filter(Boolean)
    .join(' · ')
}

/** "2026-10-28" → "10月28日" */
export function monthDay(date: string) {
  const [, month, day] = date.split('-').map(Number)
  return `${month}月${day}日`
}
