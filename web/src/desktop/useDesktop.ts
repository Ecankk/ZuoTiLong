import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { endpoints } from '../api/endpoints'
import { queryKeys } from '../api/queries'
import { desktop, desktopErrorMessage, isDesktop } from './bridge'

export const desktopInfoKey = ['desktop', 'info'] as const

/** 桌面信息（数据位置、版本、Codex 路径）；不在桌面里时不请求。 */
export function useDesktopInfo() {
  return useQuery({
    queryKey: desktopInfoKey,
    queryFn: desktop.info,
    enabled: isDesktop(),
    staleTime: 60_000,
    retry: false,
  })
}

export const BUSY_HINT = '做题龙正在处理任务，等它完成后再改。'

/**
 * 会让后台重启或停下的桌面操作：先查一次 /api/tasks，有任务在运行就直接提示；
 * 没有再交给外壳（外壳自己还会再查一次，以它的返回为准）。成功后窗口会切到外壳的加载页。
 */
export function useDesktopRestart<A extends unknown[]>(action: (...args: A) => Promise<unknown>) {
  const client = useQueryClient()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const run = async (...args: A) => {
    setError(null)
    setPending(true)
    try {
      const tasks = await client.fetchQuery({
        queryKey: queryKeys.tasks,
        queryFn: endpoints.tasks,
        staleTime: 0,
      })
      if (tasks.active) {
        setError(BUSY_HINT)
        return false
      }
    } catch {
      // 查不到任务状态时交给外壳判断
    }
    try {
      await action(...args)
      setDone(true)
      return true
    } catch (e) {
      setError(desktopErrorMessage(e))
      return false
    } finally {
      setPending(false)
    }
  }
  return { run, pending, error, done, reset: () => setError(null) }
}
