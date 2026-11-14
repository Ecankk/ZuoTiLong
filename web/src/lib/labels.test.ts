import { expect, it } from 'vitest'
import type { Access } from '../api/types'
import { practiceSource, sourceName } from './labels'

const access = (change: Partial<Access>): Access => ({
  id: 'b1',
  math_type: 1,
  year: '2021',
  number: 3,
  reserved: false,
  can_view: true,
  confirmed: false,
  cross_checked: false,
  masked: false,
  analysis_allowed: false,
  reason: '',
  ...change,
})

it('labels exam questions with year, category and number', () => {
  expect(sourceName(access({}))).toBe('2021 数学一')
  expect(practiceSource(access({}))).toBe('2021 数学一 · 第 3 题')
})

it('never shows undefined or 第 0 题 for collection questions without exam identity', () => {
  expect(practiceSource(access({ math_type: 0, year: '', number: 0 }))).toBe('')
  expect(practiceSource(access({ math_type: undefined, year: undefined, number: undefined }))).toBe(
    '',
  )
  expect(practiceSource(access({ math_type: null, year: null, number: 12 }))).toBe('第 12 题')
})

it('names the book and chapter for collection questions once the backend sends them', () => {
  const collection = (extra: Record<string, unknown>) =>
    ({ ...access({ math_type: 0, year: '', number: 0 }), ...extra }) as Access
  expect(
    practiceSource(
      collection({
        collection_label: '张宇1000题',
        book: { part: '强化篇', chapter: '第1章 函数极限与连续', number: '3' },
      }),
    ),
  ).toBe('张宇1000题 · 强化篇 第1章 · 第 3 题')
  expect(practiceSource(collection({ collection_label: '张宇1000题', book: null }))).toBe(
    '张宇1000题',
  )
  expect(practiceSource(collection({ book: { part: null, chapter: null, number: null } }))).toBe('')
})

it('does not repeat the part when the collection name already contains it', () => {
  const collection = (extra: Record<string, unknown>) =>
    ({ ...access({ math_type: 0, year: '', number: 0 }), ...extra }) as Access
  expect(
    practiceSource(
      collection({
        collection_label: '张宇1000题基础篇',
        book: { part: '基础篇', chapter: '第1章 函数极限与连续', number: '7' },
      }),
    ),
  ).toBe('张宇1000题基础篇 · 第1章 · 第 7 题')
  expect(
    practiceSource(
      collection({
        collection_label: '张宇1000题测试卷',
        book: { part: '测试卷', chapter: null, number: '2' },
      }),
    ),
  ).toBe('张宇1000题测试卷 · 第 2 题')
})
