import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { useAtoms, useOverview, useTrends } from '../../api/queries'
import type {
  ChapterConclusion,
  DisplayState,
  Distribution,
  Overview,
  ProfileNode,
  ProfileSubject,
  WeakSpot,
} from '../../api/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { ErrorState } from '../../components/ui/ErrorState'
import { PageHeader } from '../../components/ui/PageHeader'
import { Skeleton } from '../../components/ui/Skeleton'
import { cx } from '../../lib/cx'
import { ProfileBatchPanel } from './ProfileBatch'
import {
  evidenceDate,
  evidenceLink,
  isHistorical,
  stageLabel,
  weakSpotCounts,
  weakSpotLoss,
  weakSpotsNote,
} from '../../lib/profile'
import { FirstErrorCard } from './FirstErrorCard'
import styles from './ProfilePage.module.css'

/* ---------- 共用：状态、阶段、出处链接 ---------- */

const stateText: Record<DisplayState, string> = {
  mastered: '初步掌握',
  learning: '学习中',
  weak: '薄弱',
  no_record: '无记录',
}
const order: DisplayState[] = ['mastered', 'learning', 'weak', 'no_record']
const distKey: Record<DisplayState, keyof Distribution> = {
  mastered: 'mastered',
  learning: 'learning',
  weak: 'weak',
  no_record: 'no_record',
}

function Legend() {
  return (
    <div className={styles.legend}>
      {order.map((s) => (
        <span key={s}>
          <i className={styles[s]} />
          {stateText[s]}
        </span>
      ))}
      <span className={styles.legendNote}>无记录：做过相关题后才会有判断</span>
    </div>
  )
}

function DistBar({ d, thin = false }: { d: Distribution; thin?: boolean }) {
  const total = d.mastered + d.learning + d.weak + d.no_record
  return (
    <span className={cx(styles.bar, thin && styles.thin)} aria-hidden>
      {total > 0 &&
        order.map((s) => {
          const n = d[distKey[s]]
          return n > 0 ? (
            <i key={s} className={styles[s]} style={{ width: `${(n / total) * 100}%` }} />
          ) : null
        })}
    </span>
  )
}

/** 行尾只写一个最要紧的数：有薄弱写薄弱数，否则写有记录的考点数；完整分布放在悬停提示里 */
const distSummary = (d: Distribution) => {
  const observed = d.mastered + d.learning + d.weak
  if (observed + d.no_record === 0) return '暂无考点数据'
  return d.weak > 0 ? `${d.weak} 个薄弱` : observed > 0 ? `${observed} 个有记录` : '还没有记录'
}

const distDetail = (d: Distribution) =>
  `初步掌握 ${d.mastered} · 学习中 ${d.learning} · 薄弱 ${d.weak} · 无记录 ${d.no_record}`

/* ---------- 第一屏：最该补的地方 ---------- */

function WeakSpotItem({
  spot,
  index,
  subjectName,
  onPractice,
}: {
  spot: WeakSpot
  index: number
  subjectName?: string
  onPractice: () => void
}) {
  const loss = weakSpotLoss(spot)
  const counts = weakSpotCounts(spot)
  return (
    <li className={styles.spot}>
      <span className={styles.rank}>{index + 1}</span>
      <div className={styles.spotBody}>
        <div className={styles.spotHead}>
          <strong>{spot.name}</strong>
          {subjectName && <small>{subjectName}</small>}
          {isHistorical(spot) && <span className={styles.olderTag}>更早的试卷</span>}
        </div>
        {loss && <p className={styles.spotLoss}>{loss}</p>}
        {counts && <p className={styles.spotFacts}>{counts}</p>}
        {spot.basis && <p className={styles.basis}>{spot.basis}</p>}
        {isHistorical(spot) && spot.period_explanation && (
          <p className={styles.periodNote}>{spot.period_explanation}</p>
        )}
        {spot.evidence.length > 0 && (
          <ul className={styles.evidence} aria-label={`${spot.name}的错题`}>
            {spot.evidence.map((e, i) => {
              const to = evidenceLink(e)
              const stage = stageLabel(e.first_error_stage)
              const date = evidenceDate(e)
              const body = (
                <>
                  <span>{e.label}</span>
                  {date && <small>{date}</small>}
                  {stage && <em>首错：{stage}</em>}
                </>
              )
              return (
                <li key={i} title={e.first_error_evidence ?? undefined}>
                  {to ? <Link to={to}>{body}</Link> : <span className={styles.noLink}>{body}</span>}
                </li>
              )
            })}
          </ul>
        )}
      </div>
      <Button size="sm" variant="soft" onClick={onPractice}>
        去练习
      </Button>
    </li>
  )
}

function WeakSpots({
  overview,
  onPractice,
}: {
  overview: Overview
  onPractice: (id: string) => void
}) {
  const subjectName = (id: string) => overview.subjects.find((s) => s.id === id)?.name
  const d = overview.distribution
  const hasRecords = d.mastered + d.learning + d.weak > 0
  const note = weakSpotsNote(overview)
  return (
    <Card padded className={styles.primary} aria-label="最该补的地方">
      <div className={styles.cardHead}>
        <h2>最该补的地方</h2>
        {overview.weak_spots.length > 0 && !note && (
          <span className={styles.faint}>按近 28 天的错题排序</span>
        )}
      </div>
      {note && <p className={styles.fallback}>{note}</p>}
      {overview.weak_spots.length > 0 ? (
        <ol className={styles.spots}>
          {overview.weak_spots.map((spot, i) => (
            <WeakSpotItem
              key={spot.node_id}
              spot={spot}
              index={i}
              subjectName={subjectName(spot.subject_id)}
              onPractice={() => onPractice(spot.node_id)}
            />
          ))}
        </ol>
      ) : (
        <div className={styles.empty}>
          <strong>{hasRecords ? '还看不出明显的薄弱处' : '还没有作答记录'}</strong>
          <p>
            {hasRecords
              ? '近 28 天里还没有哪一章有能核对的错题。多做几道题或分析一份新试卷后，这里会列出最该补的章节。'
              : '上传做过的试卷、做几道练习后，这里会按章列出最该补的地方。没做过的章节不会被当成薄弱。'}
          </p>
        </div>
      )}
    </Card>
  )
}

/* ---------- 次要：三张结论卡 ---------- */

function ConclusionCard({
  label,
  tone,
  conclusion,
  reason,
}: {
  label: string
  tone: 'weak' | 'strong'
  conclusion: ChapterConclusion | null
  reason: string | null
}) {
  return (
    <section className={cx(styles.conclusion, styles[tone])} aria-label={label}>
      <small>{label}</small>
      {conclusion ? (
        <>
          <strong>{conclusion.name}</strong>
          <p>{conclusion.basis}</p>
        </>
      ) : (
        <p className={styles.unavailable}>{reason ?? '记录还不够，暂时不下结论。'}</p>
      )}
    </section>
  )
}

function Conclusions({ overview }: { overview: Overview }) {
  const { conclusions: raw } = overview
  // 同一个信息只说一次：“最需要补的一章”和排行第一项相同就不再单独成卡
  const sameAsTop = raw.weakest_chapter?.node_id === overview.weak_spots[0]?.node_id
  const c = sameAsTop ? { ...raw, weakest_chapter: null } : raw
  const comparison = c.independent_correct_comparison
  // 都没有结论时只留一句，不摆空卡
  if (!c.weakest_chapter && !c.strongest_chapter && !comparison) {
    const reasons = [
      ...new Set(
        [
          sameAsTop ? null : c.unavailable_reasons.weakest_chapter,
          c.unavailable_reasons.strongest_chapter,
          c.unavailable_reasons.independent_correct_comparison,
        ].filter((r): r is string => Boolean(r)),
      ),
    ]
    return (
      <Card padded aria-label="结论">
        <p className={styles.noConclusion}>
          记录还不够，暂时不下“哪一章强、哪一章弱、有没有进步”的结论。
          {reasons.length > 0 && ` ${reasons.join(' ')}`}
        </p>
      </Card>
    )
  }
  return (
    <div className={cx(styles.conclusions, sameAsTop && styles.two)}>
      {!sameAsTop && (
        <ConclusionCard
          label="哪一章最需要补"
          tone="weak"
          conclusion={c.weakest_chapter}
          reason={c.unavailable_reasons.weakest_chapter}
        />
      )}
      <ConclusionCard
        label="哪一章相对稳"
        tone="strong"
        conclusion={c.strongest_chapter}
        reason={c.unavailable_reasons.strongest_chapter}
      />
      <section className={cx(styles.conclusion, styles.progressTone)} aria-label="有没有进步">
        <small>有没有进步</small>
        {comparison ? (
          <>
            <strong>
              独立做对 {comparison.current.independent_correct} 次
              <span className={styles.delta}>
                {comparison.delta === 0
                  ? '和前 4 周一样'
                  : `比前 4 周${comparison.delta > 0 ? '多' : '少'} ${Math.abs(comparison.delta)} 次`}
              </span>
            </strong>
            <p>{comparison.basis}</p>
          </>
        ) : (
          <p className={styles.unavailable}>
            {c.unavailable_reasons.independent_correct_comparison ?? '记录还不够，暂时不比较。'}
          </p>
        )}
      </section>
    </div>
  )
}

/* ---------- 科目 → 章，展开章时才取原子热力格 ---------- */

function Heatmap({ chapterId }: { chapterId: string }) {
  const { data, error, isPending, refetch } = useAtoms(chapterId)
  if (isPending) return <p className={styles.faint}>正在读取这一章的考点…</p>
  if (error) return <ErrorState inline error={error} onRetry={() => void refetch()} />
  const items = data.items
  if (items.length === 0)
    return (
      <p className={styles.heatEmpty}>这一章暂时没有可显示的考点，考点目录整理好后会出现在这里。</p>
    )
  return (
    <div className={styles.heat}>
      <div className={styles.cells} role="list" aria-label={`${data.node.name}的考点`}>
        {items.map((atom: ProfileNode) => (
          <Link
            key={atom.id}
            role="listitem"
            to={`/topics/${encodeURIComponent(atom.id)}`}
            className={cx(styles.cell, styles[atom.display_state])}
            title={`${atom.name}：${stateText[atom.display_state]}（${atom.state_reason}）`}
            aria-label={`${atom.name}：${stateText[atom.display_state]}`}
          />
        ))}
      </div>
      <p className={styles.faint}>
        每格一个考点，点开看考点详情。
        {data.total > items.length && `共 ${data.total} 个，这里显示前 ${items.length} 个。`}
      </p>
    </div>
  )
}

function SubjectTree({
  subjects,
  initialOpen,
}: {
  subjects: ProfileSubject[]
  initialOpen?: string
}) {
  const [openSubject, setOpenSubject] = useState<string | null>(
    initialOpen ?? subjects[0]?.id ?? null,
  )
  const [openChapter, setOpenChapter] = useState<string | null>(null)
  return (
    <div className={styles.tree}>
      {subjects.map((s) => {
        const open = s.id === openSubject
        return (
          <div key={s.id} className={styles.subject}>
            <button
              type="button"
              className={styles.line}
              aria-expanded={open}
              title={distDetail(s.distribution)}
              onClick={() => setOpenSubject(open ? null : s.id)}
            >
              <ChevronRight
                size={14}
                className={cx(styles.caret, open && styles.open)}
                aria-hidden
              />
              <span className={styles.name}>{s.name}</span>
              <DistBar d={s.distribution} />
              <span className={styles.summary}>{distSummary(s.distribution)}</span>
            </button>
            {open &&
              s.chapters.map((c) => {
                const expanded = c.id === openChapter
                return (
                  <div key={c.id} className={styles.chapter}>
                    <button
                      type="button"
                      className={cx(styles.line, styles.chapterLine)}
                      aria-expanded={expanded}
                      title={distDetail(c.distribution)}
                      onClick={() => setOpenChapter(expanded ? null : c.id)}
                    >
                      <ChevronRight
                        size={12}
                        className={cx(styles.caret, expanded && styles.open)}
                        aria-hidden
                      />
                      <span className={styles.name}>{c.name}</span>
                      <DistBar d={c.distribution} thin />
                      <span className={styles.summary}>{distSummary(c.distribution)}</span>
                    </button>
                    {expanded && <Heatmap chapterId={c.id} />}
                  </div>
                )
              })}
          </div>
        )
      })}
    </div>
  )
}

/* ---------- 趋势：折叠，展开才请求 ---------- */

/** shown：页面底部已经显示的说明，趋势里不再重复 */
function TrendChart({ shown = [] }: { shown?: string[] }) {
  const { data, error, isPending, refetch } = useTrends(true, 12)
  if (isPending) return <p className={styles.faint}>正在读取…</p>
  if (error) return <ErrorState inline error={error} onRetry={() => void refetch()} />
  const weeks = data.weekly.map((w) => {
    const sum = (
      k: 'independent_correct' | 'assisted_correct' | 'independence_unknown_correct' | 'wrong',
    ) => w.sources.exam[k] + w.sources.practice[k] + w.sources.free_practice[k]
    return {
      label: w.week_start.slice(5).replace('-', '/'),
      complete: w.complete,
      independent: sum('independent_correct'),
      other: sum('assisted_correct') + sum('independence_unknown_correct'),
      wrong: sum('wrong'),
    }
  })
  const max = Math.max(1, ...weeks.map((w) => w.independent + w.other + w.wrong))
  const t = data.totals
  const unplaced =
    (data.unplaced_by_precision?.month.attempts ?? 0) +
    (data.unplaced_by_precision?.unknown.attempts ?? 0)
  return (
    <div>
      <div
        className={styles.trend}
        role="img"
        aria-label="每周作答，按独立做对、其他做对、做错分段"
      >
        {weeks.map((w) => (
          <div key={w.label} className={cx(styles.week, !w.complete && styles.partialWeek)}>
            <div className={styles.bars}>
              <i className={styles.tWrong} style={{ height: `${(w.wrong / max) * 100}%` }} />
              <i className={styles.tOther} style={{ height: `${(w.other / max) * 100}%` }} />
              <i
                className={styles.tIndependent}
                style={{ height: `${(w.independent / max) * 100}%` }}
              />
            </div>
            <small>{w.label}</small>
          </div>
        ))}
      </div>
      <div className={styles.legend}>
        <span>
          <i className={styles.tIndependent} />
          独立做对
        </span>
        <span>
          <i className={styles.tOther} />
          看过答案后做对 / 独立性未知
        </span>
        <span>
          <i className={styles.tWrong} />
          做错
        </span>
      </div>
      <p className={styles.faint}>
        近 {data.period.weeks} 周：独立做对 {t.independent_correct}，看过答案后做对{' '}
        {t.assisted_correct}
        {t.independence_unknown_correct > 0 && `，独立性未知 ${t.independence_unknown_correct}`}
        ，做错 {t.wrong}。最后一周还没过完。
      </p>
      {unplaced > 0 && (
        <p className={styles.faint}>
          另有 {unplaced} 次作答的日期只到月份或记不清，没算进每周统计。
        </p>
      )}
      {data.limitations
        .filter((l) => !shown.includes(l))
        .map((l, i) => (
          <p key={i} className={styles.faint}>
            {l}
          </p>
        ))}
    </div>
  )
}

/* ---------- 页面 ---------- */

export function ProfilePage() {
  const { data: overview, error, isPending, refetch } = useOverview()
  const [batchChapter, setBatchChapter] = useState<string | null>(null)
  const [trendOpen, setTrendOpen] = useState(false)
  const header = (
    <PageHeader title="画像" subtitle="按做过的题统计。看过答案后做对的单独计算，不算独立掌握。" />
  )
  if (isPending)
    return (
      <>
        {header}
        <Skeleton variant="rows" rows={4} />
      </>
    )
  if (error)
    return (
      <>
        {header}
        <ErrorState
          error={error}
          onRetry={() => void refetch()}
          back={{ to: '/', label: '回到首页' }}
        />
      </>
    )
  const firstWeak = overview.weak_spots[0]
  return (
    <>
      {header}
      <div className={styles.stack}>
        <WeakSpots overview={overview} onPractice={(id) => setBatchChapter(id)} />

        <FirstErrorCard summary={overview.first_error_summary} />

        {batchChapter && (
          <Card padded aria-label="按画像来一组">
            <div className={styles.cardHead}>
              <h2>
                练这一章：
                {overview.subjects.flatMap((s) => s.chapters).find((c) => c.id === batchChapter)
                  ?.name ?? overview.weak_spots.find((w) => w.node_id === batchChapter)?.name}
              </h2>
              <Button size="sm" variant="ghost" onClick={() => setBatchChapter(null)}>
                收起
              </Button>
            </div>
            <ProfileBatchPanel
              key={batchChapter}
              overview={overview}
              initialChapter={batchChapter}
            />
          </Card>
        )}

        <Conclusions overview={overview} />

        <Card padded aria-label="科目和章节">
          <div className={styles.cardHead}>
            <h2>科目和章节</h2>
          </div>
          {overview.study_type === null && (
            <p className={styles.notice}>
              还没有选备考类别，这里显示全部目录。<Link to="/settings">去设置 →</Link>
            </p>
          )}
          <Legend />
          <SubjectTree subjects={overview.subjects} initialOpen={firstWeak?.subject_id} />
        </Card>

        <Card padded aria-label="每周趋势">
          <button
            type="button"
            className={styles.foldHead}
            aria-expanded={trendOpen}
            onClick={() => setTrendOpen(!trendOpen)}
          >
            <ChevronRight
              size={16}
              className={cx(styles.caret, trendOpen && styles.open)}
              aria-hidden
            />
            <h2>每周作答趋势</h2>
            <span className={styles.faint}>
              本周作答 {overview.home_stats.attempts_this_week} 道，独立做对{' '}
              {overview.home_stats.independent_correct_this_week} 道
            </span>
          </button>
          {trendOpen && <TrendChart shown={overview.limitations} />}
        </Card>

        {overview.limitations.length > 0 && (
          <div className={styles.limitations}>
            {overview.limitations.map((l, i) => (
              <p key={i}>{l}</p>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
