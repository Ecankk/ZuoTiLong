import { useSyncExternalStore } from 'react'

/** 和本地服务的连接状态：SSE 断开超过一小会儿才算“中断”，避免一闪而过的提示 */
export type ConnectionState = 'ok' | 'lost'

let state: ConnectionState = 'ok'
const listeners = new Set<() => void>()

export function setConnection(next: ConnectionState) {
  if (next === state) return
  state = next
  listeners.forEach((listener) => listener())
}

export const getConnection = () => state

export function useConnection(): ConnectionState {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    getConnection,
    getConnection,
  )
}
