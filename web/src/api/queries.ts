import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { endpoints, type BankFilter, type PaperScope, type PracticeGrouping } from './endpoints'
import type { PreferencesChange } from './types'

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

export const CHECK_AGAIN_MS = 4000

/** 本机可用模型；正在检查时稍后再读一次。 */
export const useAgentModels = () => {
  // Codex 状态变化（如刚登录）时换一个 key，重新读取模型列表
  const { data: tasks } = useTasks()
  return useQuery({
    queryKey: ['agent-models', tasks?.availability.status],
    queryFn: endpoints.agentModels,
    enabled: tasks !== undefined,
    staleTime: 0,
    refetchInterval: (query) =>
      query.state.data?.status === 'checking' && query.state.dataUpdateCount < 2
        ? CHECK_AGAIN_MS
        : false,
  })
}

export const usePaperSummary = (paperId: string) =>
  useQuery({
    queryKey: ['papers', paperId, 'summary'],
    queryFn: () => endpoints.paperSummary(paperId),
  })

export const useDataStatus = () =>
  useQuery({ queryKey: ['data-status'], queryFn: endpoints.dataStatus, staleTime: 0 })

/**
 * 写入操作：成功后让相关资源失效。SSE 也会通知外部变更，这里先失效以便立即刷新。
 */
export function useAction<TArgs, TResult>(
  action: (args: TArgs) => Promise<TResult>,
  invalidate: readonly (readonly string[])[],
) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: action,
    onSuccess: () => {
      for (const key of invalidate) void client.invalidateQueries({ queryKey: key })
    },
  })
}

export const useSavePreferences = () =>
  useAction(
    (change: PreferencesChange) => endpoints.savePreferences(change),
    [queryKeys.preferences, ['practices'], ['profile'], ['knowledge', 'topic']],
  )

export const useImportPaper = () =>
  useAction(
    ({ file, title, examDate }: { file: File; title: string; examDate: string }) =>
      endpoints.importPaper(file, title, examDate),
    [['papers'], queryKeys.tasks],
  )

/* ---------- 题库与考点（第一段对应 SSE 的 bank / knowledge 资源） ---------- */

export const useBank = (filter: BankFilter, offset: number, limit: number) =>
  useQuery({
    queryKey: [
      'bank',
      filter.collection,
      filter.mathType,
      filter.year,
      filter.topic,
      filter.q ?? '',
      offset,
      limit,
    ],
    queryFn: () => endpoints.bank(filter, offset, limit),
    enabled: Boolean(filter.collection),
    placeholderData: keepPreviousData,
  })

/* 自由练习：第一段 'bank'，题库资源变化或查看解析后一起刷新 */
export const useFreePractice = (bankId: string) =>
  useQuery({
    queryKey: ['bank', bankId, 'practice'],
    queryFn: () => endpoints.freePractice(bankId),
    retry: false,
  })

export const useFreeAttempts = (bankId: string, offset: number, limit: number) =>
  useQuery({
    queryKey: ['bank', bankId, 'practice', 'attempts', offset, limit],
    queryFn: () => endpoints.freeAttempts(bankId, offset, limit),
    placeholderData: keepPreviousData,
  })

export const useProfile = () => useQuery({ queryKey: ['profile'], queryFn: endpoints.profile })

export const useBankCollections = () =>
  useQuery({ queryKey: ['bank', 'collections'], queryFn: endpoints.bankCollections })

export const useBankTopics = (ids: string[]) =>
  useQuery({
    queryKey: ['bank', 'topics', ...ids],
    queryFn: () => endpoints.bankTopics(ids),
    enabled: ids.length > 0,
  })

/** 目录很少变化，取一次后长期缓存 */
export const useCatalog = (enabled = true) =>
  useQuery({
    queryKey: ['knowledge', 'catalog'],
    queryFn: endpoints.catalog,
    staleTime: Infinity,
    enabled,
  })

export const useTopic = (topicId: string | undefined) =>
  useQuery({
    queryKey: ['knowledge', 'topic', topicId ?? ''],
    queryFn: () => endpoints.topic(topicId ?? ''),
    enabled: Boolean(topicId),
  })
