import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, postJson, request } from './client'

afterEach(() => vi.unstubAllGlobals())

const respond = (status: number, body: unknown) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }))

describe('request', () => {
  it('returns parsed JSON', async () => {
    vi.stubGlobal('fetch', respond(200, { ok: true }))
    await expect(request('/api/x')).resolves.toEqual({ ok: true })
  })

  it('surfaces the server message as ApiError', async () => {
    vi.stubGlobal('fetch', respond(409, { error: '这份试卷正在分析' }))
    await expect(request('/api/x')).rejects.toEqual(new ApiError('这份试卷正在分析', 409))
  })

  it('falls back to a plain message when the body has none', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('oops', { status: 500 })))
    await expect(request('/api/x')).rejects.toMatchObject({ message: '操作没有完成，请稍后再试' })
  })

  it('sends JSON bodies with a content type', async () => {
    const fetch = respond(200, {})
    vi.stubGlobal('fetch', fetch)
    await postJson('/api/x', { a: 1 })
    const init = fetch.mock.calls[0][1] as RequestInit
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
    expect(init.body).toBe('{"a":1}')
  })
})
