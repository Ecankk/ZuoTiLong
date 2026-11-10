import { describe, expect, it } from 'vitest'
import { buildConvention, fallbackDefault, parseConvention } from './convention'

describe('marking convention', () => {
  it('recognizes the default text as black pen / red pen', () => {
    expect(parseConvention(fallbackDefault, fallbackDefault)).toEqual({
      exam: '黑',
      mark: '红',
      note: '',
    })
  })

  it('round-trips pen colors and a note', () => {
    const text = buildConvention(fallbackDefault, { exam: '蓝', mark: '绿', note: '铅笔草稿不算' })
    expect(text.split('\n')[0]).toMatch(/^蓝色手写笔迹为考试时的作答/)
    expect(text.split('\n')[1]).toMatch(/^绿色手写笔迹为事后批改/)
    expect(text.endsWith('\n补充说明：铅笔草稿不算')).toBe(true)
    expect(parseConvention(text, fallbackDefault)).toEqual({
      exam: '蓝',
      mark: '绿',
      note: '铅笔草稿不算',
    })
  })

  it('returns null for hand-edited text', () => {
    expect(parseConvention('我用铅笔作答', fallbackDefault)).toBeNull()
  })
})
