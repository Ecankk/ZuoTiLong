/** 本地服务请求封装：统一把错误转成面向用户的中文说明。 */

export class ApiError extends Error {
  readonly status: number
  /** 后端给出的结构化原因（如自由练习 403 的 masked / reserved）；没有时为 undefined */
  readonly reason?: string

  constructor(message: string, status: number, reason?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.reason = reason
  }
}

type ErrorBody = Record<string, unknown> | null

const text = (value: unknown) => (typeof value === 'string' && value.trim() ? value : undefined)

/**
 * 从错误响应体取说明和原因，兼容几种写法：
 * {error: '…', reason?} / {detail: '…'} / {detail: {message|error, reason}} / {error: {message, reason}}
 */
export function parseErrorBody(data: ErrorBody): { message?: string; reason?: string } {
  if (!data || typeof data !== 'object') return {}
  const nested = [data.detail, data.error].find(
    (value): value is Record<string, unknown> => !!value && typeof value === 'object',
  )
  return {
    message: text(data.error) ?? text(data.detail) ?? text(nested?.message) ?? text(nested?.error),
    reason: text(data.reason) ?? text(nested?.reason),
  }
}

const fallbackMessage = '操作没有完成，请稍后再试'

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (typeof init.body === 'string') headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as ErrorBody
    const { message, reason } = parseErrorBody(data)
    throw new ApiError(message ?? fallbackMessage, response.status, reason)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) })
}
