import { invoke } from '@tauri-apps/api/core'

/**
 * 桌面外壳桥接（docs/frontend-api.md「桌面外壳桥接」）。
 *
 * 只有原生动作走这里：打开文件夹、选择 codex.exe、保存后重启、更改数据位置。业务数据仍走 HTTP。
 * 外壳只给当前后端的确切地址授权这六个命令；不在桌面里（浏览器开发、测试）时这些入口全部隐藏。
 */

export type DesktopInfo = {
  schema: 'zuotilong.desktop-info/v1'
  app: {
    name: '做题龙'
    version: string
    commit: string | null
    tauri: string
    webview2: string | null
    os: string
  }
  data: {
    root: string
    workspace: string
    library: string
    is_default_root: boolean
    logs: string
    locator: string
  }
  /** configured_path 为 null：自动查找（PATH → 官方安装位置） */
  codex: { configured_path: string | null }
}

export type CodexPick = {
  pick_id: string
  path: string
  version: string | null
  probe: 'ok' | 'failed'
  message: string | null
}

export type FolderTarget = 'data_root' | 'workspace' | 'library' | 'logs' | 'licenses'

export type DesktopErrorCode =
  'io_error' | 'missing' | 'dialog_failed' | 'stale_pick' | 'busy' | 'not_available' | 'unknown'

export class DesktopError extends Error {
  readonly code: DesktopErrorCode
  constructor(code: DesktopErrorCode, message: string) {
    super(message)
    this.code = code
  }
}

const fallbackMessage: Record<string, string> = {
  busy: '做题龙正在处理任务，等它完成后再改。',
  stale_pick: '请重新选择 codex.exe。',
  missing: '这个文件夹不存在。',
  dialog_failed: '没能打开选择窗口，请再试一次。',
  io_error: '没能完成这一步，请再试一次。',
}

/** 是否运行在做题龙桌面外壳里 */
export function isDesktop(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

/** 外壳失败时 reject `{code, message}`（中文，可直接显示）；统一成 DesktopError。 */
function toError(raw: unknown): DesktopError {
  if (raw && typeof raw === 'object' && 'code' in raw) {
    const { code, message } = raw as { code?: unknown; message?: unknown }
    const known = typeof code === 'string' ? code : 'unknown'
    const text =
      typeof message === 'string' && /[一-鿿]/.test(message)
        ? message
        : (fallbackMessage[known] ?? fallbackMessage.io_error)
    return new DesktopError(known as DesktopErrorCode, text)
  }
  return new DesktopError('unknown', fallbackMessage.io_error)
}

async function call<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (!isDesktop()) throw new DesktopError('not_available', '只有桌面版做题龙才能这样操作。')
  try {
    return await invoke<T>(command, args)
  } catch (raw) {
    throw toError(raw)
  }
}

export const desktop = {
  info: () => call<DesktopInfo>('desktop_info'),
  openFolder: (target: FolderTarget) => call<null>('desktop_open_folder', { target }),
  /** 用户取消选择时返回 null（不是错误） */
  pickCodex: () => call<CodexPick | null>('desktop_pick_codex'),
  saveCodex: (choice: { pick_id: string } | { auto: true }) =>
    call<{ status: 'restarting' }>('desktop_save_codex', choice),
  restartBackend: () => call<{ status: 'restarting' }>('desktop_restart_backend'),
  relocate: () => call<{ status: 'stopping' }>('desktop_relocate'),
}

export function desktopErrorMessage(error: unknown): string {
  return error instanceof DesktopError ? error.message : fallbackMessage.io_error
}
