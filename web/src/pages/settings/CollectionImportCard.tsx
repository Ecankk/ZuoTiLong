import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError } from '../../api/client'
import { endpoints } from '../../api/endpoints'
import type { CollectionPackReport } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import styles from './SettingsPage.module.css'

const catalogText: Record<CollectionPackReport['catalog']['status'], string> = {
  current: '考点目录已兼容，不需要改动',
  upgrade: '导入时会升级考点目录（只增加新内容，不改动已有考点）',
  keep_current: '保留本机当前的考点目录',
  conflict: '考点目录有冲突，不能导入',
}

const kindText: Record<string, string> = {
  exam: '真题',
  book: '教辅',
  other: '其他',
  example: '示例',
}

/** 后端错误换成用户能照着做的话 */
export function packError(error: Error) {
  if (!(error instanceof ApiError)) return error.message
  if (error.status === 404) return '暂存的题集包已失效，请重新选择文件预演。'
  if (error.status === 413) return '题集包太大：压缩包最多 1 GB，解压后最多 2 GB、3 万个文件。'
  if (error.status === 409) {
    if (/过期|变化/.test(error.message)) return '预演已过期：题库在这期间有变化，请重新预演。'
    if (/冲突/.test(error.message)) return `不能导入：${error.message}`
    return '做题龙正在维护题库或有任务在进行，请稍后再试。'
  }
  if (error.status === 400) return `这个题集包不能使用：${error.message}`
  return error.message
}

const when = (iso?: string) => (iso ? new Date(iso).toLocaleString('zh-CN', { hour12: false }) : '')

function Report({ report }: { report: CollectionPackReport }) {
  const { counts } = report
  const kindConflict = report.collection_conflicts.find((c) => 'existing_kind' in c)
  const moved = report.collection_conflicts.filter((c) => 'bank_id' in c).length
  return (
    <div className={styles.packReport}>
      <dl className={styles.facts}>
        <div className={styles.factRow}>
          <dt>题集</dt>
          <dd>
            {report.collection.name}
            {kindText[report.collection.kind] && `（${kindText[report.collection.kind]}）`}
          </dd>
        </div>
        {report.package_version && (
          <div className={styles.factRow}>
            <dt>包版本</dt>
            <dd>{report.package_version.slice(0, 8)}</dd>
          </div>
        )}
        {report.created_at && (
          <div className={styles.factRow}>
            <dt>生成时间</dt>
            <dd>{when(report.created_at)}</dd>
          </div>
        )}
        <div className={styles.factRow}>
          <dt>题数</dt>
          <dd>
            共 {counts.total} 题：可用 {counts.ready}
            {counts.needs_review > 0 && ` · 待核 ${counts.needs_review}`}
            {counts.needs_catalog > 0 && ` · 缺考点 ${counts.needs_catalog}`}
            {counts.unannotated > 0 && ` · 未标注 ${counts.unannotated}`}
          </dd>
        </div>
        <div className={styles.factRow}>
          <dt>和本机相比</dt>
          <dd>
            新增 {report.added.length} 题 · 更新 {report.updated.length} 题 · 未变{' '}
            {report.unchanged.length} 题
          </dd>
        </div>
        <div className={styles.factRow}>
          <dt>考点目录</dt>
          <dd className={report.catalog.status === 'conflict' ? styles.warn : undefined}>
            {catalogText[report.catalog.status] ?? report.catalog.status}
          </dd>
        </div>
      </dl>
      {(kindConflict || moved > 0) && (
        <div className={styles.warnBox} role="alert">
          {kindConflict && 'existing_kind' in kindConflict && (
            <p>
              本机已有同一个题集，但类型不同（本机是
              {kindText[kindConflict.existing_kind] ?? kindConflict.existing_kind}，包里是
              {kindText[kindConflict.requested_kind] ?? kindConflict.requested_kind}），不能导入。
            </p>
          )}
          {moved > 0 && <p>有 {moved} 道题在本机已经属于其他题集，不能导入。</p>}
        </div>
      )}
    </div>
  )
}

/** 设置页“导入题集”：选 zip → 预演 → 确认来源后导入。 */
export function CollectionImportCard() {
  const client = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [trusted, setTrusted] = useState(false)
  const preview = useMutation({ mutationFn: (pack: File) => endpoints.previewCollectionPack(pack) })
  const confirm = useMutation({
    mutationFn: (report: CollectionPackReport) => endpoints.confirmCollectionPack(report),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['bank'] })
      void client.invalidateQueries({ queryKey: ['knowledge'] })
      void client.invalidateQueries({ queryKey: ['data-status'] })
    },
  })
  const report = preview.data
  const blocked =
    !report || report.collection_conflicts.length > 0 || report.catalog.status === 'conflict'

  const choose = (next: File | null) => {
    setFile(next)
    setTrusted(false)
    confirm.reset()
    if (next) preview.mutate(next)
    else preview.reset()
  }
  const start = () => {
    if (!report || confirm.isPending) return
    confirm.mutate(report)
  }
  const done = confirm.data

  return (
    <Card padded className={styles.section} aria-label="导入题集">
      <h2>导入题集</h2>
      <p>
        别人整理好的题集包（.zip）可以导入到本机题库。先检查包里有什么、和本机比有哪些变化，确认后再导入。
      </p>
      <div className={styles.row}>
        <label className={styles.fileButton}>
          {file ? '换一个文件' : '选择题集包'}
          <input
            type="file"
            accept=".zip,application/zip"
            aria-label="选择题集包"
            disabled={confirm.isPending}
            onChange={(event) => {
              choose(event.target.files?.[0] ?? null)
              event.target.value = ''
            }}
          />
        </label>
        {file && <span className={styles.note}>{file.name}</span>}
        {preview.isPending && <span className={styles.note}>正在检查题集包…</span>}
      </div>

      {preview.error && (
        <p className={styles.error} role="alert">
          {packError(preview.error)}
        </p>
      )}

      {report && !done && (
        <>
          <Report report={report} />
          {!blocked && (
            <>
              <p className={styles.note}>
                {report.trust_notice
                  ? '导入即表示你信任这个题集包的来源：包里的题目、考点目录和标注会直接进入本机题库。做题龙只能检查文件完整、没被改动，不能证明是谁发布的，也不能保证题目和答案都正确。'
                  : '导入即表示你信任这个题集包的来源。'}
              </p>
              <label className={styles.switchRow}>
                <input
                  type="checkbox"
                  checked={trusted}
                  disabled={confirm.isPending}
                  onChange={(event) => setTrusted(event.target.checked)}
                />
                我了解并信任这个题集包的来源
              </label>
              <div className={styles.row}>
                <Button variant="primary" disabled={!trusted || confirm.isPending} onClick={start}>
                  {confirm.isPending ? '正在导入…' : '导入这个题集'}
                </Button>
                {confirm.isPending && (
                  <span className={styles.note} role="status">
                    正在导入，题多时需要几分钟。期间可以继续浏览，但先不要关闭做题龙。
                  </span>
                )}
              </div>
            </>
          )}
        </>
      )}

      {confirm.error && (
        <div className={styles.row}>
          <p className={styles.error} role="alert">
            {packError(confirm.error)}
          </p>
          {file &&
            confirm.error instanceof ApiError &&
            (confirm.error.status === 404 || /过期|变化/.test(confirm.error.message)) && (
              <Button size="sm" onClick={() => choose(file)}>
                重新预演
              </Button>
            )}
        </div>
      )}

      {done && (
        <p className={styles.saved} role="status">
          已导入“{done.collection.name}”：新增 {done.added.length} 题，更新 {done.updated.length}{' '}
          题，未变 {done.unchanged.length} 题。
          {done.backup?.path && ` 导入前已自动备份题库，备份在 ${done.backup.path}。`}
        </p>
      )}
    </Card>
  )
}
