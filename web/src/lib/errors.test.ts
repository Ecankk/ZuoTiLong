import { expect, it } from 'vitest'
import { ApiError } from '../api/client'
import {
  BUSY_MESSAGE,
  isBridgeBusy,
  plainTaskError,
  friendlyError,
  isOffline,
  OFFLINE_MESSAGE,
  SERVER_MESSAGE,
  TIMEOUT_MESSAGE,
} from './errors'

it('maps network failures, timeouts and server errors to fixed Chinese messages', () => {
  expect(friendlyError(new TypeError('Failed to fetch'))).toBe(OFFLINE_MESSAGE)
  expect(isOffline(new TypeError('Failed to fetch'))).toBe(true)
  expect(friendlyError(new DOMException('timed out', 'TimeoutError'))).toBe(TIMEOUT_MESSAGE)
  expect(friendlyError(new ApiError('Internal Server Error', 500))).toBe(SERVER_MESSAGE)
  expect(friendlyError(new ApiError('题库出错了', 502))).toBe(SERVER_MESSAGE)
})

it('keeps Chinese details from the backend and replaces English ones', () => {
  expect(friendlyError(new ApiError('这份试卷已归档', 409))).toBe('这份试卷已归档')
  expect(friendlyError(new ApiError('Conflict', 409))).toMatch(/现在不能这样操作/)
  expect(friendlyError(new ApiError('Not Found', 404))).toMatch(/不存在/)
  expect(friendlyError(new ApiError('', 413))).toMatch(/文件太大/)
  expect(friendlyError(new Error('boom'))).toBe(SERVER_MESSAGE)
  expect(friendlyError(undefined)).toBe(SERVER_MESSAGE)
})

it('turns the backend “stop and retry” busy refusal into plain words everywhere', () => {
  const busy = new ApiError('请等待当前任务交付或停止后重试', 409)
  expect(isBridgeBusy(busy)).toBe(true)
  expect(friendlyError(busy)).toBe(BUSY_MESSAGE)
  expect(friendlyError(busy)).not.toMatch(/停止|交付/)
  // 其他中文 409 说明照常显示
  const other = new ApiError('这份试卷已经有分析或练习记录', 409)
  expect(isBridgeBusy(other)).toBe(false)
  expect(friendlyError(other)).toBe('这份试卷已经有分析或练习记录')
})

it('rewrites the same sentence inside saved task failures', () => {
  expect(plainTaskError('请等待当前任务交付或停止后重试')).not.toMatch(/停止|交付/)
  expect(plainTaskError('题目切图缺失')).toBe('题目切图缺失')
})
