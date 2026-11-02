import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

/**
 * 服务端推送（SSE）。事件格式以接口契约为准；暂定每条消息带 resource 字段，
 * 对应 queryKeys 的第一段，收到后让该资源的缓存失效并重新获取。
 */
export type ServerEvent = { resource: string } & Record<string, unknown>

export function subscribeServerEvents(url: string, onEvent: (event: ServerEvent) => void) {
  const source = new EventSource(url)
  source.onmessage = (message: MessageEvent<string>) => {
    onEvent(JSON.parse(message.data) as ServerEvent)
  }
  return () => source.close()
}

/** url 为 null 时不订阅（接口就绪前使用本地演示数据）。 */
export function useServerEvents(url: string | null) {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!url) return
    return subscribeServerEvents(url, (event) => {
      void queryClient.invalidateQueries({ queryKey: [event.resource] })
    })
  }, [url, queryClient])
}
