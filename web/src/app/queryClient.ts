import { QueryClient } from '@tanstack/react-query'

/** 桌面应用：数据变化由服务端推送驱动，不在窗口聚焦时重复拉取。 */
export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
    },
  })
}
