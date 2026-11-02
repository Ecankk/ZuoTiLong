import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { endpoints, type PaperScope, type PracticeGrouping } from './endpoints'
import type { Preferences } from './types'

/**
 * query key 第一段对应 SSE resources.changed 的资源名（papers/questions/practices/preferences），
 * 收到变更时按第一段整体失效。
 */
export const queryKeys = {
  tasks: ['tasks'] as const,
  papers: (archived: PaperScope) => ['papers', 'list', archived] as const,
  paper: (paperId: string) => ['papers', paperId] as const,
  paperQuestions: (paperId: string) => ['questions', 'paper', paperId] as const,
  question: (questionId: string) => ['questions', questionId] as const,
  practices: (groupBy: PracticeGrouping, includeInactive: boolean) =>
    ['practices', 'list', groupBy, includeInactive] as const,
  practice: (practiceId: string) => ['practices', practiceId] as const,
  preferences: ['preferences'] as const,
}

export const useTasks = () => useQuery({ queryKey: queryKeys.tasks, queryFn: endpoints.tasks })

export const usePapers = (archived: PaperScope) =>
  useQuery({ queryKey: queryKeys.papers(archived), queryFn: () => endpoints.papers(archived) })

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

export const usePractices = (groupBy: PracticeGrouping, includeInactive = false) =>
  useQuery({
    queryKey: queryKeys.practices(groupBy, includeInactive),
    queryFn: () => endpoints.practices(groupBy, includeInactive),
  })

export const usePractice = (practiceId: string | undefined) =>
  useQuery({
    queryKey: queryKeys.practice(practiceId ?? ''),
    queryFn: () => endpoints.practice(practiceId ?? ''),
    enabled: Boolean(practiceId),
  })

export const usePreferences = () =>
  useQuery({ queryKey: queryKeys.preferences, queryFn: endpoints.preferences })

export function useSavePreferences() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ current, change }: { current: Preferences; change: Partial<Preferences> }) =>
      endpoints.savePreferences(current, change),
    onSuccess: (saved) => {
      client.setQueryData(queryKeys.preferences, saved)
      // 备考类别影响练习的遮挡规则
      void client.invalidateQueries({ queryKey: ['practices'] })
    },
  })
}

export function useImportPaper() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ file, title, examDate }: { file: File; title: string; examDate: string }) =>
      endpoints.importPaper(file, title, examDate),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['papers'] })
      void client.invalidateQueries({ queryKey: queryKeys.tasks })
    },
  })
}
