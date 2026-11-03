import { QueryClient } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { tasks } from '../mocks/data'
import { applyServerEvent, subscribeServerEvents } from './events'
import { queryKeys } from './queries'

class FakeEventSource {
  static last: FakeEventSource
  listeners = new Map<string, (message: MessageEvent<string>) => void>()
  closed = false
  constructor(readonly url: string) {
    FakeEventSource.last = this
  }
  addEventListener(name: string, listener: (message: MessageEvent<string>) => void) {
    this.listeners.set(name, listener)
  }
  emit(name: string, data: unknown) {
    this.listeners.get(name)?.(new MessageEvent(name, { data: JSON.stringify(data) }))
  }
  close() {
    this.closed = true
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('subscribeServerEvents', () => {
  it('parses named events and closes on unsubscribe', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const onEvent = vi.fn()
    const unsubscribe = subscribeServerEvents('/api/events', onEvent)
    const data = { epoch: 'e1', seq: 2, resources: ['practices'] }
    FakeEventSource.last.emit('resources.changed', data)
    expect(onEvent).toHaveBeenCalledWith({ event: 'resources.changed', data })
    unsubscribe()
    expect(FakeEventSource.last.closed).toBe(true)
  })
})

describe('applyServerEvent', () => {
  it('stores task summaries from snapshots', () => {
    const client = new QueryClient()
    const epoch = applyServerEvent(
      client,
      { event: 'snapshot', data: { epoch: 'e1', seq: 1, tasks } },
      null,
    )
    expect(epoch).toBe('e1')
    expect(client.getQueryData(queryKeys.tasks)).toEqual(tasks)
  })

  it('invalidates the changed resources', () => {
    const client = new QueryClient()
    const spy = vi.spyOn(client, 'invalidateQueries')
    applyServerEvent(
      client,
      { event: 'resources.changed', data: { epoch: 'e1', seq: 3, resources: ['practices'] } },
      'e1',
    )
    expect(spy).toHaveBeenCalledWith({ queryKey: ['practices'] })
  })

  it('refreshes everything after a server restart', () => {
    const client = new QueryClient()
    const spy = vi.spyOn(client, 'invalidateQueries')
    applyServerEvent(client, { event: 'snapshot', data: { epoch: 'e2', seq: 1, tasks } }, 'e1')
    expect(spy).toHaveBeenCalledWith()
  })
})
