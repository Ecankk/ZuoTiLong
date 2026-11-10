import { useQuery } from '@tanstack/react-query'
import { request } from '../../api/client'
import { endpoints } from '../../api/endpoints'
import { useAction, useDataStatus } from '../../api/queries'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { ErrorState } from '../../components/ui/ErrorState'
import { friendlyError } from '../../lib/errors'
import styles from './SettingsPage.module.css'

const size = (bytes: number) =>
  bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(1)} GB`
    : bytes >= 1024 ** 2
      ? `${(bytes / 1024 ** 2).toFixed(1)} MB`
      : `${Math.max(1, Math.round(bytes / 1024))} KB`

/** 给学生看的两项；后台记录（会话数据库）属于技术细节，不显示 */
const dbLabel = { learning: '学习记录', library: '题库与考点' } as const

function when(iso: string | null) {
  if (!iso) return '还没有备份'
  const date = new Date(iso)
  return date.toLocaleString('zh-CN', { hour12: false })
}

/** GET /api/maintenance/backups：本机已有的备份（key 挂在 data-status 下，备份后一起刷新） */
const useBackups = () =>
  useQuery({
    queryKey: ['data-status', 'backups'],
    queryFn: () =>
      request<{ backups: { name: string; bytes: number }[] }>('/api/maintenance/backups'),
  })

/** 数据与备份：备份时间、数据大小、“立即备份”，以及恢复说明。原始路径在高级设置里。 */
export function DataCard() {
  const { data, error, isPending, refetch } = useDataStatus()
  const { data: backups } = useBackups()
  const backup = useAction(() => endpoints.backup(), [['data-status']])
  const count = backups?.backups.length ?? 0
  return (
    <Card padded className={styles.section} aria-label="数据与备份">
      <h2>数据与备份</h2>
      <p>你的试卷、照片、分析和练习记录都只保存在这台电脑上。建议定期备份。</p>
      {error && <ErrorState inline error={error} onRetry={() => void refetch()} />}
      {isPending && <p className={styles.note}>正在读取…</p>}
      {data && (
        <>
          <dl className={styles.facts}>
            <dt>最近备份</dt>
            <dd>{when(data.last_backup_at)}</dd>
            {count > 0 && (
              <>
                <dt>已有备份</dt>
                <dd>{count} 份</dd>
              </>
            )}
            {(Object.keys(dbLabel) as (keyof typeof dbLabel)[]).map((key) => (
              <div key={key} className={styles.factRow}>
                <dt>{dbLabel[key]}</dt>
                <dd>{data.databases[key].exists ? size(data.databases[key].bytes) : '还没有'}</dd>
              </div>
            ))}
          </dl>
          {!data.library_exists && (
            <p className={styles.warnBox}>
              找不到题库所在的文件夹，题库和考点可能无法显示。位置可以在“高级设置”里查看。
            </p>
          )}
          {data.invalid_file_references.count > 0 && (
            <p className={styles.warnBox}>
              {`有 ${data.invalid_file_references.count} 个文件找不到或位置不对，相关的原卷切图或照片可能无法显示；文件本身没有被删除。`}
            </p>
          )}
          {data.path_migration.pending && (
            <p className={styles.warnBox}>
              {[
                data.path_migration.ready_count > 0 &&
                  `有 ${data.path_migration.ready_count} 个文件位置需要更新，请按配置教程运行一次路径整理（整理前会自动备份）。`,
                data.path_migration.unresolved_count > 0 &&
                  `有 ${data.path_migration.unresolved_count} 个文件位置待整理，请按配置教程运行一次路径整理（整理前会自动备份）。`,
              ]
                .filter(Boolean)
                .join('')}
            </p>
          )}
        </>
      )}
      <div className={styles.row}>
        <Button disabled={backup.isPending} onClick={() => backup.mutate(undefined)}>
          {backup.isPending ? '正在备份…' : '立即备份'}
        </Button>
        {backup.data && (
          <span className={styles.saved} role="status">
            已备份 {backup.data.files} 个文件
          </span>
        )}
      </div>
      {backup.error && <p className={styles.error}>{friendlyError(backup.error)}</p>}
      <p className={styles.note}>
        备份包含原卷、照片、分析和练习记录，保存在数据文件夹的“备份”里。
      </p>
      <section className={styles.restore} aria-label="从备份恢复">
        <h3>从备份恢复</h3>
        <p>
          在做题龙里直接恢复的功能会在之后的版本提供。在那之前请妥善保留备份，不要删除；以后恢复时会另建一份数据，不会覆盖你现在的记录。
        </p>
      </section>
    </Card>
  )
}

/** 高级设置里的数据位置：给需要手动拷贝或排查问题时看。 */
export function DataPaths() {
  const { data } = useDataStatus()
  if (!data) return null
  return (
    <section className={styles.subsection} aria-label="数据文件位置">
      <h3>数据文件位置</h3>
      <p>手动拷贝数据或排查问题时才需要。移动这些文件夹前请先关闭做题龙。</p>
      <dl className={styles.facts}>
        <dt>个人数据</dt>
        <dd className={styles.path}>{data.data_dir}</dd>
        <dt>题库</dt>
        <dd className={styles.path}>
          {data.library_dir}
          {!data.library_exists && <span className={styles.warn}>（找不到这个文件夹）</span>}
        </dd>
      </dl>
    </section>
  )
}
