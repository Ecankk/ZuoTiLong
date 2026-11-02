import { afterEach, expect, it, vi } from 'vitest'
import { subscribeServerEvents } from './events'

class FakeEventSource {
  static last: FakeEventSource
  onmessage: ((message: MessageEvent<string>) => void) | null = null
  closed = false
  constructor(readonly url: string) {
    FakeEventSource.last = this
  }
  close() {
    this.closed = true
  }
}

afterEach(() => vi.unstubAllGlobals())

it('parses messages and closes on unsubscribe', () => {
  vi.stubGlobal('EventSource', FakeEventSource)
  const onEvent = vi.fn()
  const unsubscribe = subscribeServerEvents('/api/events', onEvent)
  const source = FakeEventSource.last
  source.onmessage?.(new MessageEvent('message', { data: '{"resource":"practice"}' }))
  expect(onEvent).toHaveBeenCalledWith({ resource: 'practice' })
  unsubscribe()
  expect(source.closed).toBe(true)
})
