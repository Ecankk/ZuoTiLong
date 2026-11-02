/** 本地服务请求封装：统一把错误转成面向用户的中文说明。 */

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const fallbackMessage = '操作没有完成，请稍后再试'

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (typeof init.body === 'string') headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as {
      error?: unknown
      detail?: unknown
    } | null
    const message = data?.error ?? data?.detail
    throw new ApiError(typeof message === 'string' ? message : fallbackMessage, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) })
}
