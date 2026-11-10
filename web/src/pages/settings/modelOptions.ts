import type { AgentModels } from '../../api/types'

export type Model = AgentModels['items'][number]

/** 思考深度的中文名；接口给的是固定英文档位 */
const effortNames: Record<string, string> = {
  none: '不思考',
  minimal: '最快',
  low: '快速',
  medium: '标准',
  high: '仔细',
  xhigh: '非常仔细',
}

/** 认不出的档位不显示英文原文，按它在列表里的位置叫“第 N 档” */
export function effortLabel(effort: string, efforts: string[] = []) {
  if (effortNames[effort]) return effortNames[effort]
  const index = efforts.indexOf(effort)
  return index >= 0 ? `第 ${index + 1} 档` : '其他档位'
}

/** 按名称前缀分组：gpt-6-luna → gpt-6，GPT-5.1-Codex → GPT-5.1，o3 → o3，其他取第一个词 */
export function modelFamily(name: string) {
  const versioned = /^([A-Za-z]+[-\s]?\d+(?:\.\d+)?)/.exec(name)
  if (versioned) return versioned[1]
  return name.split(/[-\s_/]/)[0] || name
}

export type ModelGroup = { family: string; models: Model[] }

/**
 * 模型多、而且至少有两个系列时才分组，否则返回一个没有名字的组。
 * 组的顺序按每组第一次出现的位置，保持接口给的顺序。
 */
export function groupModels(models: Model[], minimum = 7): ModelGroup[] {
  const groups = new Map<string, Model[]>()
  for (const model of models) {
    const family = modelFamily(model.name)
    groups.set(family, [...(groups.get(family) ?? []), model])
  }
  if (models.length < minimum || groups.size < 2) return [{ family: '', models }]
  return [...groups].map(([family, items]) => ({ family, models: items }))
}

/** 搜索：名称包含输入的文字（不分大小写、忽略空格和连字符） */
export function filterModels(models: Model[], query: string) {
  const norm = (text: string) => text.toLowerCase().replace(/[\s\-_]/g, '')
  const term = norm(query)
  if (!term) return models
  return models.filter((model) => norm(model.name).includes(term) || norm(model.id).includes(term))
}

/** 超过这个数量时显示搜索框 */
export const searchThreshold = 10
