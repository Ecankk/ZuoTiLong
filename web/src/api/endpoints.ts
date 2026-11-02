/**
 * 数据获取入口。接口契约确定前返回本地演示数据；对齐契约时只改这里，
 * 页面通过 queries.ts 的 hooks 使用，不直接接触请求细节。
 */
import {
  analyses,
  backgroundStatus,
  home,
  papers,
  practiceDetails,
  practiceOverview,
} from '../mocks/data'
import type {
  BackgroundStatus,
  HomeData,
  PaperDetail,
  PracticeDetail,
  PracticeOverview,
  QuestionAnalysis,
} from './types'

const local = <T>(value: T): Promise<T> => Promise.resolve(structuredClone(value))

export const endpoints = {
  background: (): Promise<BackgroundStatus> => local(backgroundStatus),
  home: (): Promise<HomeData> => local(home),
  paper: (paperId: string): Promise<PaperDetail | null> =>
    local(papers.find((paper) => paper.id === paperId) ?? null),
  analysis: (paperId: string, number: string): Promise<QuestionAnalysis | null> =>
    local(analyses.find((item) => item.paperId === paperId && item.number === number) ?? null),
  practiceOverview: (): Promise<PracticeOverview> => local(practiceOverview),
  practiceDetail: (practiceId: string): Promise<PracticeDetail | null> =>
    local(practiceDetails.find((item) => item.id === practiceId) ?? null),
}
