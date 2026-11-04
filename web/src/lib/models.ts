/** 推理强度从浅到深的顺序，用来在换模型时找最接近的档位。 */
const effortOrder = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh']

const labels: Record<string, string> = {
  xhigh: '最深入（较慢）',
  high: '深入',
  medium: '标准',
  low: '快速',
}

/** 中文名；不认识的档位原样显示。 */
export const effortLabel = (effort: string) => labels[effort] ?? effort

/**
 * 当前档位不在新模型支持的列表里时，选最接近的；距离相同取更深的一档。
 * 当前档位或候选都不在已知顺序里时，取第一个。
 */
export function closestEffort(current: string, efforts: string[]) {
  if (efforts.includes(current)) return current
  const from = effortOrder.indexOf(current)
  let best = efforts[0] ?? current
  let distance = Infinity
  if (from < 0) return best
  for (const effort of efforts) {
    const index = effortOrder.indexOf(effort)
    if (index < 0) continue
    const d = Math.abs(index - from)
    if (d < distance || (d === distance && index > effortOrder.indexOf(best))) {
      best = effort
      distance = d
    }
  }
  return best
}
