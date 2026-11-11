import { expect, it } from 'vitest'
import {
  dateUpdateFields,
  examDateLabel,
  examDateLine,
  sortByExamDate,
  uploadDateFields,
} from './examDate'

it('formats each precision without treating YYYY-MM as a full date', () => {
  expect(examDateLabel({ exam_date: '2026-10-18', exam_date_precision: 'day' })).toBe(
    '2026年10月18日',
  )
  expect(examDateLabel({ exam_date: '2026-10', exam_date_precision: 'month' })).toBe('约2026年10月')
  // 旧接口没有 precision：按值的形状判断
  expect(examDateLabel({ exam_date: '2026-10' })).toBe('约2026年10月')
  expect(examDateLabel({ exam_date: '2026-10-18' })).toBe('2026年10月18日')
  expect(
    examDateLine({
      exam_date: null,
      exam_date_precision: 'unknown',
      exam_date_unknown_reason: 'forgotten',
    }),
  ).toBe('作答日期记不清')
  expect(examDateLine({ exam_date: null })).toBe('作答日期未知')
})

it('maps the choices to request fields', () => {
  expect(uploadDateFields({ mode: 'none', value: '' })).toBeUndefined()
  expect(uploadDateFields({ mode: 'forgotten', value: '' })).toEqual({
    exam_date: null,
    exam_date_precision: 'unknown',
    exam_date_unknown_reason: 'forgotten',
  })
  expect(dateUpdateFields({ mode: 'none', value: '' })).toEqual({
    exam_date: null,
    exam_date_precision: 'unknown',
    exam_date_unknown_reason: 'not_provided',
  })
  expect(dateUpdateFields({ mode: 'day', value: '2026-01-02' })).toEqual({
    exam_date: '2026-01-02',
    exam_date_precision: 'day',
    exam_date_unknown_reason: null,
  })
})

it('sorts known dates newest first and unknown dates last', () => {
  const ids = sortByExamDate([
    { id: 'u', exam_date: null },
    { id: 'm', exam_date: '2026-10', exam_date_precision: 'month' as const },
    { id: 'd', exam_date: '2026-10-05', exam_date_precision: 'day' as const },
    { id: 'old', exam_date: '2025-01-01', exam_date_precision: 'day' as const },
  ]).map((item) => item.id)
  expect(ids).toEqual(['d', 'm', 'old', 'u'])
})
