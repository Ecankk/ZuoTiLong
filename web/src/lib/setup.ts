import type { TasksResponse } from '../api/types'

/** 应用内配置教程页（不依赖外网） */
export const SETUP_GUIDE_PATH = '/help/setup'

const messages: Record<string, string> = {
  not_installed:
    '这台电脑还没有安装做题龙需要的 Codex。按教程完成一次性设置后，分析和批改会自动开始。',
  not_logged_in: '做题龙需要的 Codex 还没有登录。按教程登录一次后，分析和批改会自动开始。',
  disabled: '学习服务现在没有启用，分析和批改暂时不能进行；已保存的内容仍然可以查看。',
}

/** AI 服务未就绪时给学生看的一句话；后端原始短句只在是中文且没有对应说法时才用 */
export function setupMessage(
  availability: Pick<TasksResponse['availability'], 'reason' | 'message'>,
) {
  const known = messages[availability.reason ?? '']
  if (known) return known
  const raw = availability.message?.trim() ?? ''
  return raw && /[一-鿿]/.test(raw) && raw.length > 8
    ? raw
    : '做题龙暂时不能分析和批改，已保存的内容仍然可以查看。'
}
