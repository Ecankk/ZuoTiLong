import { useQuery } from '@tanstack/react-query'
import { endpoints } from './endpoints'

/** 第一段与服务端推送的 resource 对应，便于按资源整体失效。 */
export const queryKeys = {
  background: ['background'] as const,
  home: ['home'] as const,
  paper: (paperId: string) => ['papers', paperId] as const,
  analysis: (paperId: string, number: string) => ['papers', paperId, 'questions', number] as const,
  practiceOverview: ['practice'] as const,
  practiceDetail: (practiceId: string) => ['practice', practiceId] as const,
}

export const useBackgroundStatus = () =>
  useQuery({ queryKey: queryKeys.background, queryFn: endpoints.background })

export const useHome = () => useQuery({ queryKey: queryKeys.home, queryFn: endpoints.home })

export const usePaper = (paperId: string) =>
  useQuery({ queryKey: queryKeys.paper(paperId), queryFn: () => endpoints.paper(paperId) })

export const useAnalysis = (paperId: string, number: string) =>
  useQuery({
    queryKey: queryKeys.analysis(paperId, number),
    queryFn: () => endpoints.analysis(paperId, number),
  })

export const usePracticeOverview = () =>
  useQuery({ queryKey: queryKeys.practiceOverview, queryFn: endpoints.practiceOverview })

export const usePracticeDetail = (practiceId: string) =>
  useQuery({
    queryKey: queryKeys.practiceDetail(practiceId),
    queryFn: () => endpoints.practiceDetail(practiceId),
    enabled: Boolean(practiceId),
  })
