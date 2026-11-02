import { useQuery } from '@tanstack/react-query'
import { endpoints, type PracticeGrouping } from './endpoints'

/**
 * query key 第一段对应 SSE resources.changed 的资源名（papers/questions/practices/...），
 * 收到变更时按第一段整体失效。
 */
export const queryKeys = {
  tasks: ['tasks'] as const,
  home: ['home'] as const,
  paper: (paperId: string) => ['papers', paperId] as const,
  paperQuestions: (paperId: string) => ['questions', 'paper', paperId] as const,
  question: (questionId: string) => ['questions', questionId] as const,
  practices: (groupBy: PracticeGrouping) => ['practices', 'list', groupBy] as const,
  practice: (practiceId: string) => ['practices', practiceId] as const,
}

export const useTasks = () => useQuery({ queryKey: queryKeys.tasks, queryFn: endpoints.tasks })

export const useHome = () => useQuery({ queryKey: queryKeys.home, queryFn: endpoints.home })

export const usePaper = (paperId: string) =>
  useQuery({ queryKey: queryKeys.paper(paperId), queryFn: () => endpoints.paper(paperId) })

export const usePaperQuestions = (paperId: string) =>
  useQuery({
    queryKey: queryKeys.paperQuestions(paperId),
    queryFn: () => endpoints.paperQuestions(paperId),
  })

export const useQuestion = (questionId: string | undefined) =>
  useQuery({
    queryKey: queryKeys.question(questionId ?? ''),
    queryFn: () => endpoints.question(questionId ?? ''),
    enabled: Boolean(questionId),
  })

export const usePractices = (groupBy: PracticeGrouping) =>
  useQuery({ queryKey: queryKeys.practices(groupBy), queryFn: () => endpoints.practices(groupBy) })

export const usePractice = (practiceId: string | undefined) =>
  useQuery({
    queryKey: queryKeys.practice(practiceId ?? ''),
    queryFn: () => endpoints.practice(practiceId ?? ''),
    enabled: Boolean(practiceId),
  })
