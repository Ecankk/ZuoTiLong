import { afterEach, expect, it, vi } from 'vitest'
import { prefersReducedMotion, scrollBehavior } from './motion'

afterEach(() => vi.unstubAllGlobals())

function stubMatchMedia(reduce: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduce && query.includes('prefers-reduced-motion: reduce'),
    media: query,
  }))
}

it('scrolls smoothly by default', () => {
  stubMatchMedia(false)
  expect(prefersReducedMotion()).toBe(false)
  expect(scrollBehavior()).toBe('smooth')
})

it('jumps without animation when the system asks for reduced motion', () => {
  stubMatchMedia(true)
  expect(prefersReducedMotion()).toBe(true)
  expect(scrollBehavior()).toBe('auto')
})
