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

it('labels collection questions with collection, chapter and original number', () => {
  expect(
    practiceSource(
      access({
        math_type: 0,
        year: '',
        number: 0,
        collection_label: '张宇1000题',
        book: { part: '强化篇', chapter: '第45章', number: '12' },
      }),
    ),
  ).toBe('张宇1000题 · 第45章 · 第 12 题')
  expect(
    practiceSource(access({ math_type: 0, year: '', number: 0, collection_label: '张宇1000题' })),
  ).toBe('张宇1000题')
})
