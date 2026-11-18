import { ApiError } from '../api/client'

/** 后端给的说明是中文时才原样显示；英文或空的一律换成通用说明 */
const hasChinese = (text: string) => /[一-鿿]/.test(text)

export const OFFLINE_MESSAGE = '连不上做题龙，请确认做题龙还开着，稍后再试。'
export const TIMEOUT_MESSAGE = '做题龙这次响应太慢了，请稍后再试。'
export const SERVER_MESSAGE = '做题龙出了点问题，请稍后再试。'
export const BUSY_MESSAGE = '做题龙正在处理另一项任务，完成后再试。'

/**
 * 后台正在执行 AI 任务时拒绝写入：409 + “请等待当前任务交付或停止后重试”。
 * 运行中的任务用户停不了，这句原文看不懂，统一换成白话（BUSY_MESSAGE）。
 */
const BRIDGE_BUSY = /请等待当前任务交付|停止后重试/

export function isBridgeBusy(error: unknown) {
  return error instanceof ApiError && error.status === 409 && BRIDGE_BUSY.test(error.message ?? '')
}

/** 任务/批次失败原因（后台保存的文字）里出现同一句时也换成白话 */
export function plainTaskError(text: string) {
  return BRIDGE_BUSY.test(text)
    ? '做题龙当时正在处理另一项任务，这一项没能开始，可以再试一次。'
    : text
}

/** 断网、服务没开、请求被浏览器拦下：fetch 抛 TypeError（如 “Failed to fetch”） */
export function isOffline(error: unknown) {
  return error instanceof TypeError && !(error instanceof ApiError)
}

export function isTimeout(error: unknown) {
  return (
    error instanceof DOMException && (error.name === 'TimeoutError' || error.name === 'AbortError')
  )
}

/**
 * 把任何错误换成给学生看的一句中文：
 * 断网 / 超时 / 404 / 409 / 413 / 5xx 各有固定说法；后端明确给出的中文说明（detail/error）优先。
 * 永远不返回英文原始报错。
 */
export function friendlyError(error: unknown): string {
  if (error == null) return SERVER_MESSAGE
  if (isOffline(error)) return OFFLINE_MESSAGE
  if (isTimeout(error)) return TIMEOUT_MESSAGE
  if (error instanceof ApiError) {
    const detail = error.message?.trim() ?? ''
    if (error.status >= 500) return SERVER_MESSAGE
    if (isBridgeBusy(error)) return BUSY_MESSAGE
    if (detail && hasChinese(detail)) return detail
    if (error.status === 404) return '要找的内容不存在，可能已经被删除或调整。'
    if (error.status === 409) return '现在不能这样操作，可能有任务正在进行，请稍后再试。'
    if (error.status === 413) return '文件太大了，请换一个小一点的文件。'
    if (error.status === 403) return '这项内容现在不能查看。'
    return '操作没有完成，请检查后再试。'
  }
  if (error instanceof Error && hasChinese(error.message)) return error.message
  return SERVER_MESSAGE
}
