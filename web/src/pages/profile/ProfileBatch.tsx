import { useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { endpoints, requestId } from '../../api/endpoints'
import { useAction, useProfileBatch } from '../../api/queries'
import type { Overview, ProfileBatchSize } from '../../api/types'
import { Button, ButtonLink } from '../../components/ui/Button'
import { ButtonRow } from '../../components/ui/ButtonRow'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Segmented } from '../../components/ui/Segmented'
import { clientStateKeys, useClientState } from '../../lib/clientState'
import { friendlyError, plainTaskError } from '../../lib/errors'
import styles from './ProfileBatch.module.css'

const sizes: ProfileBatchSize[] = [5, 8, 10]

/** 进行中的批次记在后端草稿里，离开页面或重开做题龙后还能看到进度 */
function useActiveBatch() {
  const state = useClientState<string | null>(clientStateKeys.profileBatch, {
    fallback: null,
    fromLegacy: (raw) => raw || undefined,
  })
  return [state.value, state.set] as const
}

/** 文档约定的跳转（source=profile&view=topic&item=首个练习）；带上 batch 只看这一组 */
export const practiceLinkForBatch = (practiceIds: string[], batchId?: string) => {
  const batch = batchId ? `&batch=${encodeURIComponent(batchId)}` : ''
  return practiceIds.length
    ? `/practice?source=profile&view=topic&item=${encodeURIComponent(practiceIds[0])}${batch}`
    : `/practice?source=profile&view=topic${batch}`
}

const categoryText = { weak: '薄弱', review_due: '该复习', uncovered: '新考点' } as const

/** 已提交的批次：选题进度 → 结果 */
function BatchProgress({ batchId, onDone }: { batchId: string; onDone: () => void }) {
  const { data: batch, error } = useProfileBatch(batchId)
  if (error)
    return (
      <div className={styles.progress} role="status">
        <p>{friendlyError(error)}</p>
        <Button size="sm" onClick={onDone}>
          重新选择
        </Button>
      </div>
    )
  if (!batch || batch.status === 'queued' || batch.status === 'selecting')
    return (
      <div className={styles.progress} role="status">
        <span className={styles.spinner} aria-hidden />
        <div>
          <strong>
            {batch?.status === 'selecting'
              ? '做题龙正在按画像挑题…'
              : '已排进任务队列，等前面的任务做完就开始挑题'}
          </strong>
          <p>一般几分钟。可以先离开这个页面，挑好后回来就能开始做。</p>
        </div>
      </div>
    )
  if (batch.status === 'ready')
    return (
      <div className={styles.progress} role="status">
        <div>
          <strong>挑好了 {batch.actual_size} 道</strong>
          {batch.targets.length > 0 && (
            <p>
              覆盖：
              {batch.targets
                .slice(0, 4)
                .map((t) => `${t.name}（${categoryText[t.category]}）`)
                .join('、')}
              {batch.targets.length > 4 && ` 等 ${batch.targets.length} 个考点`}
            </p>
          )}
          {batch.limitations.map((l, i) => (
            <p key={i} className={styles.note}>
              {l.reason}
            </p>
          ))}
          <ButtonRow className={styles.actions}>
            <ButtonLink variant="primary" to={practiceLinkForBatch(batch.practice_ids, batch.id)}>
              开始做 <ArrowRight size={16} aria-hidden />
            </ButtonLink>
            <Button variant="ghost" onClick={onDone}>
              再来一组
            </Button>
          </ButtonRow>
        </div>
      </div>
    )
  if (batch.status === 'no_candidates')
    return (
      <div className={styles.progress} role="status">
        <div>
          <strong>这次没有挑到合适的题</strong>
          {(batch.limitations.length
            ? batch.limitations
            : [{ reason: '可选的题都已经做过或被保护。' }]
          ).map((l, i) => (
            <p key={i}>{l.reason}</p>
          ))}
          <ButtonRow className={styles.actions}>
            <Button size="sm" onClick={onDone}>
              换个范围试试
            </Button>
            <ButtonLink size="sm" variant="ghost" to="/bank">
              在题库里挑题
            </ButtonLink>
          </ButtonRow>
        </div>
      </div>
    )
  return (
    <div className={styles.progress} role="status">
      <div>
        <strong>{batch.status === 'cancelled' ? '这次选题已取消' : '这次选题没有完成'}</strong>
        {batch.error && <p>{plainTaskError(batch.error)}</p>}
        <p className={styles.note}>
          {batch.status === 'failed' ? '可以在左下角的后台进度里重试，或重新选择。' : ''}
        </p>
        <Button size="sm" onClick={onDone}>
          重新选择
        </Button>
      </div>
    </div>
  )
}

/**
 * “按画像来一组”：题量 5/8/10，范围按科目或章（用 overview 里的节点 ID）。
 * 提交前确认会排一个 AI 任务；提交后显示批次进度，挑好后跳到练习页。
 */
export function ProfileBatchPanel({
  overview,
  initialChapter,
}: {
  overview: Overview
  /** 从“最该补的地方”点进来时预选这一章 */
  initialChapter?: string
}) {
  const client = useQueryClient()
  const startSubject = initialChapter
    ? overview.subjects.find((s) => s.chapters.some((c) => c.id === initialChapter))?.id
    : undefined
  const [size, setSize] = useState<ProfileBatchSize>(initialChapter ? 5 : 8)
  const [subject, setSubject] = useState<string>(startSubject ?? '')
  const [chapter, setChapter] = useState<string>(initialChapter ?? '')
  const [confirming, setConfirming] = useState(false)
  const [request, setRequest] = useState(requestId)
  const [batchId, setBatchId] = useActiveBatch()
  const eligibility = overview.profile_batch_eligibility
  const create = useAction(
    () =>
      endpoints.createProfileBatch({
        confirmed: true,
        request_id: request,
        size,
        ...(subject || chapter
          ? {
              scope: {
                ...(subject && { subject }),
                ...(chapter && { chapter_topic_id: chapter }),
              },
            }
          : {}),
      }),
    [['tasks']],
  )
  const chapters = overview.subjects.find((s) => s.id === subject)?.chapters ?? []
  const scopeName = chapter
    ? chapters.find((c) => c.id === chapter)?.name
    : overview.subjects.find((s) => s.id === subject)?.name

  if (batchId)
    return (
      <BatchProgress
        batchId={batchId}
        onDone={() => {
          setBatchId(null)
          setRequest(requestId())
          create.reset()
          void client.invalidateQueries({ queryKey: ['profile', 'overview'] })
        }}
      />
    )

  return (
    <div className={styles.panel}>
      <div className={styles.options}>
        <span className={styles.label}>题量</span>
        <Segmented<string>
          label="题量"
          items={sizes.map((n) => ({ value: String(n), label: `${n} 道` }))}
          value={String(size)}
          onChange={(value) => setSize(Number(value) as ProfileBatchSize)}
        />
        <span className={styles.label}>范围</span>
        <div className={styles.scope}>
          <Segmented<string>
            label="科目"
            items={[
              { value: '', label: '全部' },
              ...overview.subjects.map((s) => ({ value: s.id, label: s.name })),
            ]}
            value={subject}
            onChange={(value) => {
              setSubject(value)
              setChapter('')
            }}
          />
          {subject && (
            <select
              className={styles.select}
              aria-label="章"
              value={chapter}
              onChange={(event) => setChapter(event.target.value)}
            >
              <option value="">整个科目</option>
              {chapters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>
      {!eligibility.can_create && (
        <p className={styles.blocked} role="status">
          {eligibility.reason ?? '现在还不能按画像挑题。'}
          {overview.study_type === null && (
            <>
              {' '}
              <Link to="/settings">去设置备考类别 →</Link>
            </>
          )}
        </p>
      )}
      <ButtonRow className={styles.actions}>
        <Button
          variant="primary"
          disabled={!eligibility.can_create}
          onClick={() => setConfirming(true)}
        >
          <Sparkles size={16} aria-hidden /> 按画像来一组
        </Button>
        {eligibility.can_create && (
          <span className={styles.note}>
            从 {eligibility.target_counts.weak} 个薄弱、{eligibility.target_counts.review_due}{' '}
            个该复习的考点里挑，没做过的考点不算薄弱
          </span>
        )}
      </ButtonRow>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={`按画像挑 ${size} 道题？`}
        confirmLabel="开始挑题"
        pending={create.isPending}
        error={create.error ? friendlyError(create.error) : undefined}
        onConfirm={() =>
          create.mutate(undefined, {
            onSuccess: (created) => {
              setConfirming(false)
              setBatchId(created.batch_id)
              void client.invalidateQueries({ queryKey: ['profile', 'batch', created.batch_id] })
            },
          })
        }
      >
        <p>
          做题龙会排一个 AI 任务，按你的画像{scopeName ? `在“${scopeName}”里` : ''}
          挑题，一般需要几分钟。 挑好后题目会出现在“练习”里。
        </p>
        <p className={styles.note}>
          题目按薄弱、该复习、新考点大约 5:3:2 分配；可选的题不够时会少发，不会硬凑。
        </p>
      </ConfirmDialog>
    </div>
  )
}
