import { useQuery } from '@tanstack/react-query'
import { CircleAlert, CircleCheck, FolderOpen } from 'lucide-react'
import { useState } from 'react'
import { endpoints } from '../../api/endpoints'
import { Button } from '../../components/ui/Button'
import { ButtonRow } from '../../components/ui/ButtonRow'
import { Card } from '../../components/ui/Card'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import {
  desktop,
  desktopErrorMessage,
  DesktopError,
  type CodexPick,
  type FolderTarget,
} from '../../desktop/bridge'
import { useDesktopInfo, useDesktopRestart } from '../../desktop/useDesktop'
import styles from './SettingsPage.module.css'

/* 设置页里只在桌面版出现的三块：数据位置、AI 服务位置、关于里的版本与文件夹。 */

function useOpenFolder() {
  const [error, setError] = useState<string | null>(null)
  const open = async (target: FolderTarget) => {
    setError(null)
    try {
      await desktop.openFolder(target)
    } catch (e) {
      setError(desktopErrorMessage(e))
    }
  }
  return { open, error }
}

function Path({ value }: { value: string }) {
  return <dd className={styles.path}>{value}</dd>
}

/** 数据保存位置：路径配说明，可以打开文件夹、按步骤更改位置。 */
export function DesktopDataCard() {
  const { data, error } = useDesktopInfo()
  const folder = useOpenFolder()
  const relocate = useDesktopRestart(desktop.relocate)
  const [confirming, setConfirming] = useState(false)
  return (
    <Card padded className={styles.section} aria-label="数据保存位置">
      <h2>数据保存位置</h2>
      <p>
        题库和你的学习记录都保存在这台电脑的这个文件夹里。排查问题时，可以把这些位置告诉帮你的人。
      </p>
      {error && <p className={styles.error}>{desktopErrorMessage(error)}</p>}
      {data && (
        <dl className={styles.facts}>
          <dt>数据文件夹</dt>
          <Path value={data.data.root + (data.data.is_default_root ? '（默认位置）' : '')} />
          <dt>学习记录</dt>
          <Path value={data.data.workspace} />
          <dt>题库</dt>
          <Path value={data.data.library} />
        </dl>
      )}
      <ButtonRow className={styles.row}>
        <Button disabled={!data} onClick={() => void folder.open('data_root')}>
          <FolderOpen size={16} aria-hidden />
          打开数据文件夹
        </Button>
        <Button variant="ghost" disabled={!data} onClick={() => setConfirming(true)}>
          更改位置…
        </Button>
      </ButtonRow>
      {folder.error && <p className={styles.error}>{folder.error}</p>}
      <ConfirmDialog
        open={confirming}
        onOpenChange={(next) => {
          setConfirming(next)
          if (!next) relocate.reset()
        }}
        title="更改数据保存位置"
        confirmLabel={relocate.done ? '正在停下后台…' : '继续'}
        pending={relocate.pending || relocate.done}
        error={relocate.error}
        onConfirm={() => void relocate.run()}
      >
        <ol className={styles.stepsList}>
          <li>点“继续”后，做题龙会先停下后台，回到选择位置的页面。</li>
          <li>用文件资源管理器把整个数据文件夹复制到新位置（例如 D 盘）。</li>
          <li>回到做题龙，选择复制好的新文件夹。原来的文件夹会保留，核对无误后可以自己删除。</li>
        </ol>
      </ConfirmDialog>
    </Card>
  )
}

function PickResult({ pick }: { pick: CodexPick }) {
  const ok = pick.probe === 'ok'
  return (
    <div className={styles.pickBox} role="status" aria-label="选择结果">
      {ok ? (
        <CircleCheck size={20} color="var(--status-correct)" aria-hidden />
      ) : (
        <CircleAlert size={20} color="var(--status-partial)" aria-hidden />
      )}
      <div>
        <strong>{ok ? '可以使用' : '这个程序用不了'}</strong>
        <span className={styles.path}>{pick.path}</span>
        <small>
          {ok
            ? pick.version
              ? `版本：${pick.version}`
              : '已确认能正常启动'
            : (pick.message ?? '请选择官方安装的 codex.exe。')}
        </small>
      </div>
    </div>
  )
}

/** AI 服务位置：默认自动查找；也可以手动选择 codex.exe，确认能启动后再保存（保存后重启后台）。 */
export function CodexPathCard() {
  const { data } = useDesktopInfo()
  const [pick, setPick] = useState<CodexPick | null>(null)
  const [picking, setPicking] = useState(false)
  const [pickError, setPickError] = useState<string | null>(null)
  const save = useDesktopRestart((choice: { pick_id: string } | { auto: true }) =>
    desktop.saveCodex(choice).catch((e: unknown) => {
      // 选择过期：清掉旧结果，请用户重新选
      if (e instanceof DesktopError && e.code === 'stale_pick') setPick(null)
      throw e
    }),
  )
  const configured = data?.codex.configured_path ?? null
  const choose = async () => {
    setPickError(null)
    save.reset()
    setPicking(true)
    try {
      const result = await desktop.pickCodex()
      if (result) setPick(result)
    } catch (e) {
      setPickError(desktopErrorMessage(e))
    } finally {
      setPicking(false)
    }
  }
  return (
    <Card padded className={styles.section} aria-label="AI 服务位置">
      <h2>AI 服务位置</h2>
      <p>
        做题龙会自动在这台电脑上查找
        Codex。一般不需要改；如果装在了特别的位置，或者自动查找不到，可以在这里手动选择
        codex.exe。保存后后台会重新启动。
      </p>
      {data && (
        <dl className={styles.facts}>
          <dt>现在使用</dt>
          {configured ? (
            <Path value={configured} />
          ) : (
            <dd>自动查找（先找系统里登记的位置，再找官方默认安装位置）</dd>
          )}
        </dl>
      )}
      {pick && <PickResult pick={pick} />}
      <ButtonRow className={styles.row}>
        <Button disabled={!data || picking || save.pending} onClick={() => void choose()}>
          {picking ? '正在选择…' : '选择 codex.exe…'}
        </Button>
        {pick?.probe === 'ok' && (
          <Button
            variant="primary"
            disabled={save.pending || save.done}
            onClick={() => void save.run({ pick_id: pick.pick_id })}
          >
            {save.done ? '正在重启…' : '保存并重启后台'}
          </Button>
        )}
        {configured && !pick && (
          <Button
            variant="ghost"
            disabled={save.pending || save.done}
            onClick={() => void save.run({ auto: true })}
          >
            {save.done ? '正在重启…' : '恢复自动查找'}
          </Button>
        )}
      </ButtonRow>
      {pickError && <p className={styles.error}>{pickError}</p>}
      {save.error && <p className={styles.error}>{save.error}</p>}
    </Card>
  )
}

/** “关于”里桌面版额外显示的版本与文件夹入口。 */
export function DesktopAbout() {
  const { data } = useDesktopInfo()
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: endpoints.health,
    staleTime: Infinity,
  })
  const folder = useOpenFolder()
  if (!data) return null
  return (
    <>
      <dl className={styles.facts}>
        <dt>桌面程序</dt>
        <dd>v{data.app.version}</dd>
        <dt>后台服务</dt>
        <dd>{health?.version ? `v${health.version}` : '读取中…'}</dd>
        <dt>网页组件</dt>
        <dd>{data.app.webview2 ? `WebView2 ${data.app.webview2}` : '未知'}</dd>
        <dt>系统</dt>
        <dd>{data.app.os}</dd>
      </dl>
      <ButtonRow className={styles.row}>
        <Button size="sm" onClick={() => void folder.open('licenses')}>
          第三方声明
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void folder.open('logs')}>
          打开日志文件夹
        </Button>
      </ButtonRow>
      <p className={styles.note}>遇到问题时，可以把日志文件夹里的文件发给帮你排查的人。</p>
      {folder.error && <p className={styles.error}>{folder.error}</p>}
    </>
  )
}
