import { expect, it } from 'vitest'
import { closestEffort, effortLabel } from './models'

it('keeps a supported effort and otherwise picks the closest one', () => {
  expect(closestEffort('high', ['low', 'high'])).toBe('high')
  expect(closestEffort('xhigh', ['low', 'medium', 'high'])).toBe('high')
  expect(closestEffort('xhigh', ['minimal', 'low'])).toBe('low')
  expect(closestEffort('medium', ['low', 'high'])).toBe('high')
  expect(closestEffort('turbo', ['low', 'high'])).toBe('low')
})

it('names efforts in Chinese and shows unknown values as they are', () => {
  expect(effortLabel('xhigh')).toBe('最深入（较慢）')
  expect(effortLabel('low')).toBe('快速')
  expect(effortLabel('minimal')).toBe('minimal')
})
