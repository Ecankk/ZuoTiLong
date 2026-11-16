import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { endpoints } from '../api/endpoints'

/**
 * 客户端偏好与进度存到后端草稿（GET/POST /api/drafts?key=）。
 *
 * 桌面版每次启动后端端口都不同，WebView2 的 localStorage 按 origin 隔离、每次都是空的，
 * 所以“已看过引导”这类状态不能放在浏览器存储里。浏览器开发模式也走同一处。
 * 旧版本留在 localStorage 的值第一次读到时迁移过去，然后删掉，不长期保留两套。
 */
export const clientStateKeys = {
  onboardingSeen: 'zuotilong:onboarding-seen',
  profileBatch: 'zuotilong:profile-batch',
  freePracticeTimer: 'zuotilong:free-practice-show-timer',
} as const

type Options<T> = {
  /** 还没有存过时的值 */
  fallback: T
  /** 把旧 localStorage 里的字符串转成新值；返回 undefined 表示不迁移 */
  fromLegacy: (raw: string) => T | undefined
}

function takeLegacy(key: string): string | null {
  try {
    const raw = localStorage.getItem(key)
    if (raw !== null) localStorage.removeItem(key)
    return raw
  } catch {
    return null
  }
}

export const clientStateQueryKey = (key: string) => ['drafts', key] as const

async function load<T>(key: string, { fallback, fromLegacy }: Options<T>): Promise<T> {
  const stored = await endpoints.draft<T>(key)
  if (stored !== null && stored !== undefined) {
    takeLegacy(key) // 已经有新值：旧值直接丢掉
    return stored
  }
  const raw = takeLegacy(key)
  const migrated = raw === null ? undefined : fromLegacy(raw)
  if (migrated === undefined) return fallback
  try {
    await endpoints.saveDraft(key, migrated)
  } catch {
    // 迁移失败也照常用这个值；下次保存时会再写一次
  }
  return migrated
}

/**
 * 读写一项客户端状态。`ready` 为 false 时还没读到（例如首次引导要等读到后再决定显示与否）。
 * 写入先更新界面再保存，保存失败时本次打开期间仍按新值显示。
 */
export function useClientState<T>(key: string, options: Options<T>) {
  const client = useQueryClient()
  const query = useQuery({
    queryKey: clientStateQueryKey(key),
    queryFn: () => load(key, options),
    staleTime: Infinity,
    retry: 1,
  })
  const set = useCallback(
    (value: T) => {
      client.setQueryData(clientStateQueryKey(key), value)
      endpoints.saveDraft(key, value).catch(() => {
        /* 保存不了就只在这次打开期间有效 */
      })
    },
    [client, key],
  )
  return {
    value: query.data ?? options.fallback,
    ready: query.isSuccess || query.isError,
    failed: query.isError,
    set,
  }
}
