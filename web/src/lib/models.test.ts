import { expect, it } from 'vitest'
import { closestEffort } from './models'

it('keeps a supported effort and otherwise picks the closest one', () => {
  expect(closestEffort('high', ['low', 'high'])).toBe('high')
  expect(closestEffort('xhigh', ['low', 'medium', 'high'])).toBe('high')
  expect(closestEffort('xhigh', ['minimal', 'low'])).toBe('low')
  expect(closestEffort('medium', ['low', 'high'])).toBe('high')
  expect(closestEffort('turbo', ['low', 'high'])).toBe('low')
})
