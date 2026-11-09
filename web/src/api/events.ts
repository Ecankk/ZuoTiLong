import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { getConnection, setConnection } from './connection'
import { queryKeys } from './queries'
import type { TasksResponse } from './types'

/** GET /api/events 的数据事件（docs/frontend-api.md「SSE」）。 */
export type ServerEvent =
  | { event: 'snapshot'; data: { epoch: string; seq: number; tasks: TasksResponse } }
  | { event: 'tasks.changed'; data: { epoch: string; seq: number; tasks: TasksResponse } }
  | { event: 'preparation.changed'; data: { epoch: string; seq: number } }
  | { event: 'resources.changed'; data: { epoch: string; seq: number; resources: string[] } }

const eventNames: ServerEvent['event'][] = [
  'snapshot',
  'tasks.changed',
  'preparation.changed',
  'resources.changed',
]

/** 断开多久才提示“连接中断” */
export const LOST_AFTER_MS = 3000

/**
 * 订阅命名事件。断线由 EventSource 自动重连；已显示的数据保留。
 * onStatus：连上时报 'open'，出错时报 'error'（可能接着自动重连）。
 */
export function subscribeServerEvents(
  url: string,
  onEvent: (event: ServerEvent) => void,
  onStatus?: (status: 'open' | 'error') => void,
) {
  const source = new EventSource(url)
  source.addEventListener('open', () => onStatus?.('open'))
  source.addEventListener('error', () => onStatus?.('error'))
  for (const name of eventNames) {
    source.addEventListener(name, (message) => {
      onEvent({
        event: name,
        data: JSON.parse((message as MessageEvent<string>).data),
      } as ServerEvent)
    })
  }
  return () => source.close()
}

/** 把服务端事件应用到查询缓存。返回下一次比较用的 epoch。 */
export function applyServerEvent(
  client: QueryClient,
  event: ServerEvent,
  lastEpoch: string | null,
): string {
  const { epoch } = event.data
  switch (event.event) {
    case 'snapshot':
      client.setQueryData(queryKeys.tasks, event.data.tasks)
      // 服务重启（epoch 改变）后已加载的数据都需要校准
      if (lastEpoch !== null && lastEpoch !== epoch) void client.invalidateQueries()
      break
    case 'tasks.changed':
      client.setQueryData(queryKeys.tasks, event.data.tasks)
      break
    case 'resources.changed':
      for (const resource of event.data.resources) {
        void client.invalidateQueries({ queryKey: [resource] })
      }
      break
    case 'preparation.changed':
      // 原卷识别进度会改变试卷的分析状态
      void client.invalidateQueries({ queryKey: ['papers'] })
      break
  }
  return epoch
}

/** url 为 null 时不订阅（接入真实接口前使用本地演示数据）。 */
export function useServerEvents(url: string | null) {
  const client = useQueryClient()
  useEffect(() => {
    if (!url) return
    let epoch: string | null = null
    let timer: number | undefined
    const stop = subscribeServerEvents(
      url,
      (event) => {
        epoch = applyServerEvent(client, event, epoch)
        window.clearTimeout(timer)
        timer = undefined
        setConnection('ok')
      },
      (status) => {
        if (status === 'open') {
          window.clearTimeout(timer)
          timer = undefined
          // 断开后重新连上：已显示的数据可能过期，全部重新读取
          if (getConnection() === 'lost') void client.invalidateQueries()
          setConnection('ok')
        } else if (timer === undefined) {
          // 只在第一次出错时开始计时；重连期间的反复出错不重新计时
          timer = window.setTimeout(() => setConnection('lost'), LOST_AFTER_MS)
        }
      },
    )
    return () => {
      window.clearTimeout(timer)
      stop()
    }
  }, [url, client])
}
