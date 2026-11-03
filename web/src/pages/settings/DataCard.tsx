import { endpoints } from '../../api/endpoints'
import { useAction, useDataStatus } from '../../api/queries'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import styles from './SettingsPage.module.css'

const size = (bytes: number) =>
  bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(1)} GB`
    : bytes >= 1024 ** 2
      ? `${(bytes / 1024 ** 2).toFixed(1)} MB`
      : `${Math.max(1, Math.round(bytes / 1024))} KB`

const dbLabel = { learning: '学习记录', library: '题库与考点', session: '后台记录' } as const

function when(iso: string | null) {
  if (!iso) return '还没有备份'
  const date = new Date(iso)
  return date.toLocaleString('zh-CN', { hour12: false })
}

/** 数据与备份：只读状态（GET /api/data/status）加“立即备份”。 */
export function DataCard() {
  const { data, error } = useDataStatus()
  const backup = useAction(() => endpoints.backup(), [['data-status']])
  return (
    <Card padded className={styles.section} aria-label="数据与备份">
      <h2>数据与备份</h2>
      {error && <p className={styles.error}>{error.message}</p>}
      {data && (
        <>
          <dl className={styles.facts}>
            <dt>数据位置</dt>
            <dd className={styles.path}>{data.data_dir}</dd>
            <dt>题库位置</dt>
            <dd className={styles.path}>
              {data.library_dir}
              {!data.library_exists && <span className={styles.warn}>（找不到这个目录）</span>}
            </dd>
            {(Object.keys(dbLabel) as (keyof typeof dbLabel)[]).map((key) => (
              <div key={key} className={styles.factRow}>
                <dt>{dbLabel[key]}</dt>
                <dd>{data.databases[key].exists ? size(data.databases[key].bytes) : '未创建'}</dd>
              </div>
            ))}
            <dt>最近备份</dt>
            <dd>{when(data.last_backup_at)}</dd>
          </dl>
          {data.invalid_file_references.count > 0 && (
            <p className={styles.warnBox}>
              {`有 ${data.invalid_file_references.count} 个文件找不到或位置不对，相关的原卷切图或照片可能无法显示；文件本身没有被删除。`}
            </p>
          )}
          {data.path_migration.pending && (
            <p className={styles.warnBox}>
              有 {data.path_migration.ready_count} 个文件位置需要更新
              {data.path_migration.unresolved_count > 0 &&
                `，另有 ${data.path_migration.unresolved_count} 个无法自动核对`}
              。请按配置教程运行一次路径整理，整理前会自动备份。
            </p>
          )}
          <div className={styles.row}>
            <Button disabled={backup.isPending} onClick={() => backup.mutate(undefined)}>
              {backup.isPending ? '正在备份…' : '立即备份'}
            </Button>
            {backup.data && <span className={styles.saved}>已备份 {backup.data.files} 个文件</span>}
          </div>
          {backup.data && <p className={styles.path}>{backup.data.path}</p>}
          {backup.error && <p className={styles.error}>{backup.error.message}</p>}
          <p className={styles.note}>备份包含原卷、照片、分析和练习记录，请自己妥善保管。</p>
        </>
      )}
    </Card>
  )
}
