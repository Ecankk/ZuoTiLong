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

/**
 * 题集题的出处字段（后端准备补充，现在可能都没有）：
 * collection_label 如“张宇1000题”，book 如 {part:'强化篇', chapter:'第1章 函数极限与连续', number:'3'}。
 */
type CollectionSource = {
  collection_label?: string | null
  book?: { part?: string | null; chapter?: string | null; number?: string | number | null } | null
  chapter?: string | null
}

/** “第1章 函数极限与连续” → “第1章”；不是这种写法就原样返回 */
const shortChapter = (chapter: string) =>
  chapter.match(/^第\s*[\d一二三四五六七八九十百]+\s*章/)?.[0] ?? chapter

/** 题集题出处：“张宇1000题 · 强化篇 第1章 · 第 3 题”；没有任何来源字段时为空字符串 */
function collectionSource(access: Access & CollectionSource) {
  const chapter = access.book?.chapter?.trim() || access.chapter?.trim() || ''
  const label = access.collection_label?.trim() ?? ''
  // 题集名已含篇名（“张宇1000题基础篇”“……测试卷”）时不再重复显示篇名
  const part = access.book?.part?.trim() ?? ''
  const section = [part && !label.includes(part) ? part : '', chapter && shortChapter(chapter)]
    .filter(Boolean)
    .join(' ')
  const raw =
    String(access.book?.number ?? '').trim() || (access.number ? String(access.number) : '')
  const number = raw ? (/^\d+$/.test(raw) ? `第 ${raw} 题` : raw) : ''
  if (!label && !section) return ''
  return [label, section, number].filter(Boolean).join(' · ')
}

/**
 * 练习题出处：真题“2021 数学一 · 第 3 题”，题集题“张宇1000题 · 强化篇 第1章 · 第 3 题”；
 * 缺的部分不显示，全缺时为空字符串。
 */
export const practiceSource = (access: Access & CollectionSource) =>
  sourceName(access)
    ? [sourceName(access), access.number ? `第 ${access.number} 题` : '']
        .filter(Boolean)
        .join(' · ')
    : collectionSource(access) || (access.number ? `第 ${access.number} 题` : '')

/** "2026-10-28" → "10月28日" */
export function monthDay(date: string) {
  const [, month, day] = date.split('-').map(Number)
  return `${month}月${day}日`
}
