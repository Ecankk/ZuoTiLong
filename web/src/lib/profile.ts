import type { WeakSpot, WeakSpotEvidence } from '../api/types'

/** 后端保存的首错环节枚举 → 中文；已经是中文或不认识的原样显示，unknown 不显示 */
const stageText: Record<string, string> = {
  entry: '读题',
  modeling: '建模',
  formula: '公式',
  calculation: '计算',
  finalization: '收尾',
}
export const stageLabel = (stage: string | null) =>
  !stage || stage === 'unknown' ? null : (stageText[stage] ?? stage)

/** 错题出处的链接：原卷进试卷页，练习进练习，自由练习进做题页 */
export function evidenceLink(e: WeakSpotEvidence) {
  if (e.source === 'practice' && e.practice_id)
    return `/practice?item=${encodeURIComponent(e.practice_id)}`
  if (e.source === 'free_practice' && e.bank_id)
    return `/bank/${encodeURIComponent(e.bank_id)}/practice`
  // 有题号时直达题目页；没有题号只能到试卷概览
  if (e.paper_id && e.question_number)
    return `/papers/${encodeURIComponent(e.paper_id)}/questions/${encodeURIComponent(e.question_number)}`
  if (e.paper_id) return `/papers/${encodeURIComponent(e.paper_id)}`
  return null
}

/** “近 28 天做了 6 道，错 4 道 · 3 个考点要补”：不用“有效判断”这类说法 */
export const weakSpotFacts = (spot: WeakSpot) =>
  `近 28 天做了 ${spot.recent_judged} 道，错 ${spot.recent_failures} 道` +
  (spot.weak_atom_count > 0 ? ` · ${spot.weak_atom_count} 个考点要补` : '')
