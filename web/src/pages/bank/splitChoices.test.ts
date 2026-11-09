import { describe, expect, it } from 'vitest'
import { choicesAreShort, splitChoices } from './splitChoices'

describe('splitChoices', () => {
  it('splits options that each sit on their own line', () => {
    const text = '级数的收敛域为（ ）。\n\nA. $[-2,2]$\n\nB. $[-1,1]$\n\nC. $(-2,2)$\n\nD. $(-1,1)$'
    expect(splitChoices(text)).toEqual({
      stem: '级数的收敛域为（ ）。',
      choices: [
        { letter: 'A', text: '$[-2,2]$' },
        { letter: 'B', text: '$[-1,1]$' },
        { letter: 'C', text: '$(-2,2)$' },
        { letter: 'D', text: '$(-1,1)$' },
      ],
    })
  })

  it('splits options written in one paragraph but ignores letters inside formulas', () => {
    const text = '设 $A.B$ 为矩阵，则（ ） A. $A^*$ 可逆 B. $A^{-1}=A$ C．$A=B$ D、以上都不对'
    const result = splitChoices(text)
    expect(result?.stem).toBe('设 $A.B$ 为矩阵，则（ ）')
    expect(result?.choices.map((c) => c.text)).toEqual([
      '$A^*$ 可逆',
      '$A^{-1}=A$',
      '$A=B$',
      '以上都不对',
    ])
  })

  it('accepts bracketed letters', () => {
    const result = splitChoices('则（ ）\n(A) 1\n(B) 2\n(C) 3\n(D) 4')
    expect(result?.choices.map((c) => c.letter)).toEqual(['A', 'B', 'C', 'D'])
    expect(result?.choices[0].text).toBe('1')
  })

  it('returns null when the text has no options', () => {
    expect(splitChoices('求极限 $\\lim_{x\\to0} x$。')).toBeNull()
    expect(splitChoices(null)).toBeNull()
    // 字母顺序不对时不拆
    expect(splitChoices('题干\nB. 1\nA. 2')).toBeNull()
  })

  it('keeps multi-line option bodies together', () => {
    const result = splitChoices('题干\nA. 第一行\n续行\nB. 二')
    expect(result?.choices[0].text).toBe('第一行\n续行')
  })

  it('tells short options from long ones', () => {
    expect(choicesAreShort([{ letter: 'A', text: '$\\frac{1}{6},3$' }])).toBe(true)
    expect(
      choicesAreShort([
        { letter: 'A', text: '当 $f(x)$ 在 $(-1,0)$ 上单调减少，在 $(0,1)$ 上单调增加时' },
      ]),
    ).toBe(false)
  })
})
