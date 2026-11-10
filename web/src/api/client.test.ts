import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, parseErrorBody, postJson, request } from './client'

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

describe('structured error reason', () => {
  it('carries the reason from the error body (e.g. masked / reserved on free practice)', async () => {
    vi.stubGlobal('fetch', respond(403, { error: '题目未允许查看', reason: 'masked' }))
    const error = await request('/api/bank/q1/practice').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 403, reason: 'masked', message: '题目未允许查看' })
  })

  it('reads reason and message nested in detail, and leaves reason undefined when absent', () => {
    expect(parseErrorBody({ detail: { message: '属于预留卷', reason: 'reserved' } })).toEqual({
      message: '属于预留卷',
      reason: 'reserved',
    })
    expect(parseErrorBody({ error: '已归档' })).toEqual({ message: '已归档', reason: undefined })
    expect(parseErrorBody(null)).toEqual({})
  })
})
