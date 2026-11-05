import { expect, it } from 'vitest'
import { choiceLetters } from './choices'

it('finds option letters written in common styles', () => {
  expect(choiceLetters('则（ ）\n\nA. $1$\n\nB. $2$\n\nC. $3$\n\nD. $4$')).toEqual([
    'A',
    'B',
    'C',
    'D',
  ])
  expect(choiceLetters('(A) 1 (B) 2 (C) 3')).toEqual(['A', 'B', 'C'])
  expect(choiceLetters('A．极大值 B．极小值')).toEqual(['A', 'B'])
})

it('falls back to A–D when options are not in the text', () => {
  expect(choiceLetters('见图')).toEqual(['A', 'B', 'C', 'D'])
  expect(choiceLetters(undefined)).toEqual(['A', 'B', 'C', 'D'])
})
