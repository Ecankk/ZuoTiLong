import type { WeakSpot, WeakSpotEvidence } from '../api/types'
import { examDateLabel, timestampDay } from './examDate'

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

/** 后端的依据句已经写了“做了几道、错几道”时，只补一句“几个考点要补”，不重复计数 */
export const weakSpotFactsBesideBasis = (spot: WeakSpot) =>
  !spot.basis
    ? weakSpotFacts(spot)
    : spot.weak_atom_count > 0
      ? `${spot.weak_atom_count} 个考点要补`
      : ''

/* ---------- B28：近期 / 历史补位、原卷失分、错题日期 ---------- */

/** 后端给了 B28 字段才按近期/历史分开说；旧接口只有近 28 天的计数 */
const hasPeriods = (spot: WeakSpot) => spot.evidence_period !== undefined

export const isHistorical = (spot: WeakSpot) => spot.evidence_period === 'historical'

const points = (n: number) => String(Math.round(n * 10) / 10)

/** 这一项所用时段（近期或历史补位）的原卷错题、练习错题 */
function periodCounts(spot: WeakSpot) {
  const historical = isHistorical(spot)
  return {
    exam: (historical ? spot.historical_exam_failure_count : spot.recent_exam_failure_count) ?? 0,
    practice:
      (historical ? spot.historical_practice_failure_count : spot.recent_practice_failure_count) ??
      0,
    lost: historical ? spot.historical_lost_points : spot.recent_lost_points,
    unknown:
      (historical
        ? spot.historical_loss_unknown_question_count
        : spot.recent_loss_unknown_question_count) ?? 0,
  }
}

/**
 * “涉及原卷失分约 6 分（按已保存估分）”：只说这一章自己的，不跟别的章相加；
 * 分数缺失时说“分数未知”，不当 0 分。没有原卷错题时不显示。
 */
export function weakSpotLoss(spot: WeakSpot): string | null {
  if (!hasPeriods(spot)) return null
  const { exam, lost, unknown } = periodCounts(spot)
  if (exam === 0) return null
  if (lost === null || lost === undefined) return '涉及的原卷失分：分数未知'
  return (
    `涉及原卷失分约 ${points(lost)} 分（按已保存估分` +
    (unknown > 0 ? `，另有 ${unknown} 道分数未知）` : '）')
  )
}

/**
 * “原卷错 2 道 · 练习错 1 道 · 3 个考点要补”。后端依据句已经写了“做了几道、错几道”时
 * 不再重复计数，只补考点数（同一件事只说一次）；旧接口退回原来的说法。
 */
export function weakSpotCounts(spot: WeakSpot): string {
  if (!hasPeriods(spot) || spot.basis) return weakSpotFactsBesideBasis(spot)
  const { exam, practice } = periodCounts(spot)
  return [
    exam > 0 && `原卷错 ${exam} 道`,
    practice > 0 && `练习错 ${practice} 道`,
    spot.weak_atom_count > 0 && `${spot.weak_atom_count} 个考点要补`,
  ]
    .filter(Boolean)
    .join(' · ')
}

/** 首页右侧的数字：这一项所用时段一共错了几道 */
export function weakSpotWrong(spot: WeakSpot): number {
  if (!hasPeriods(spot)) return spot.recent_failures
  const { exam, practice } = periodCounts(spot)
  return exam + practice
}

/** 错题日期：原卷按作答日期的精度（日 / 月 / 未知），练习和自由练习用作答时间 */
export const evidenceDate = (e: WeakSpotEvidence) =>
  e.source === 'exam'
    ? e.exam_date_precision !== undefined
      ? examDateLabel(e)
      : null
    : timestampDay(e.occurred_at)

/** 全局首错汇总里的一条：去原卷题目或练习 */
export function firstErrorLink(e: {
  source: string
  paper_id: string | null
  question_number: string | null
  practice_id: string | null
}) {
  if (e.practice_id) return `/practice?item=${encodeURIComponent(e.practice_id)}`
  if (e.paper_id && e.question_number)
    return `/papers/${encodeURIComponent(e.paper_id)}/questions/${encodeURIComponent(e.question_number)}`
  if (e.paper_id) return `/papers/${encodeURIComponent(e.paper_id)}`
  return null
}
