import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { TasksResponse } from '../api/types'
import type { CodexPick, DesktopInfo } from '../desktop/bridge'
import { tasks } from '../mocks/data'
import { json, mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

const info = (codex: string | null = null): DesktopInfo => ({
  schema: 'zuotilong.desktop-info/v1',
  app: {
    name: '做题龙',
    version: '0.10.0',
    commit: '213965d',
    tauri: '2.12.5',
    webview2: '157.0.4341.46',
    os: 'Windows 11 (10.0.26200)',
  },
  data: {
    root: 'C:\\Users\\同学\\AppData\\Local\\ZuoTiLong',
    workspace: 'C:\\Users\\同学\\AppData\\Local\\ZuoTiLong\\workspaces\\default',
    library: 'C:\\Users\\同学\\AppData\\Local\\ZuoTiLong\\library',
    is_default_root: true,
    logs: 'C:\\Users\\同学\\AppData\\Local\\ZuoTiLong\\workspaces\\default',
    locator: 'C:\\Users\\同学\\AppData\\Local\\ZuoTiLong\\desktop.json',
  },
  codex: { configured_path: codex },
})

const okPick: CodexPick = {
  pick_id: 'pick-1',
  path: 'D:\\工具\\Codex\\codex.exe',
  version: 'codex-cli 0.130.0',
  probe: 'ok',
  message: null,
}

type Handler = (args: Record<string, unknown> | undefined) => unknown

/** 模拟外壳：只有表里的命令能用；处理函数抛出的值作为 reject（{code,message}）。 */
function shell(handlers: Record<string, Handler>) {
  const calls: { cmd: string; args: unknown }[] = []
  const invoke = vi.fn(async (cmd: string, args?: Record<string, unknown>) => {
    calls.push({ cmd, args })
    const handler = handlers[cmd]
    if (!handler) throw { code: 'not_available', message: '没有这个命令' }
    return handler(args)
  })
  vi.stubGlobal('__TAURI_INTERNALS__', { invoke, transformCallback: () => 0 })
  return calls
}

const idle: TasksResponse = { ...tasks, active: null }

function server(taskState: TasksResponse = idle) {
  const posts: string[] = []
  const fetch = mockServer({
    tasks: taskState,
    routes: (path, init) => {
      if (path === '/api/health')
        return json({ ok: true, app: 'mathlens', version: '0.10.0', data_id: 'x' })
      if (path === '/api/agent/connect' && init?.method === 'POST') {
        posts.push(path)
        return json({ status: 'idle' })
      }
      return undefined
    },
  })
  return { fetch, posts }
}

function renderAt(path: string) {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />
    </QueryClientProvider>,
  )
}

const cmds = (calls: { cmd: string }[]) => calls.map((c) => c.cmd)

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('hides every desktop entry in the browser', async () => {
  server()
  renderAt('/settings')
  expect(await screen.findByRole('region', { name: '关于' })).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: '数据保存位置' })).not.toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'AI 服务位置' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '重启后台' })).not.toBeInTheDocument()
})

it('shows data locations with explanations and reports a missing folder', async () => {
  server()
  const calls = shell({
    desktop_info: () => info(),
    desktop_open_folder: () => {
      throw { code: 'missing', message: '这个文件夹不存在' }
    },
  })
  renderAt('/settings')
  const card = await screen.findByRole('region', { name: '数据保存位置' })
  expect(await within(card).findByText(/ZuoTiLong（默认位置）/)).toBeInTheDocument()
  expect(within(card).getByText(/workspaces\\default/)).toBeInTheDocument()
  expect(card).toHaveTextContent('排查问题时')
  await userEvent.click(within(card).getByRole('button', { name: /打开数据文件夹/ }))
  expect(await within(card).findByText('这个文件夹不存在')).toBeInTheDocument()
  expect(calls.find((c) => c.cmd === 'desktop_open_folder')?.args).toEqual({ target: 'data_root' })
})

it('explains relocation first and stops when a task is running', async () => {
  server(tasks) // 默认 mock 有正在运行的任务
  const calls = shell({
    desktop_info: () => info(),
    desktop_relocate: () => ({ status: 'stopping' }),
  })
  renderAt('/settings')
  const card = await screen.findByRole('region', { name: '数据保存位置' })
  await userEvent.click(await within(card).findByRole('button', { name: '更改位置…' }))
  const dialog = await screen.findByRole('dialog', { name: '更改数据保存位置' })
  expect(dialog).toHaveTextContent('复制到新位置')
  await userEvent.click(within(dialog).getByRole('button', { name: '继续' }))
  expect(
    await within(dialog).findByText('做题龙正在处理任务，等它完成后再改。'),
  ).toBeInTheDocument()
  expect(cmds(calls)).not.toContain('desktop_relocate')
})

it('shows the shell busy answer when it disagrees with the page', async () => {
  server()
  const calls = shell({
    desktop_info: () => info(),
    desktop_relocate: () => {
      throw { code: 'busy', message: '做题龙正在处理任务，等它完成后再改。' }
    },
  })
  renderAt('/settings')
  const card = await screen.findByRole('region', { name: '数据保存位置' })
  await userEvent.click(await within(card).findByRole('button', { name: '更改位置…' }))
  const dialog = await screen.findByRole('dialog')
  await userEvent.click(within(dialog).getByRole('button', { name: '继续' }))
  expect(await within(dialog).findByText(/正在处理任务/)).toBeInTheDocument()
  expect(cmds(calls)).toContain('desktop_relocate')
})

it('checks a picked codex.exe before saving and restarts with the pick id', async () => {
  server()
  const calls = shell({
    desktop_info: () => info(),
    desktop_pick_codex: () => okPick,
    desktop_save_codex: () => ({ status: 'restarting' }),
  })
  renderAt('/settings')
  const card = await screen.findByRole('region', { name: 'AI 服务位置' })
  expect(await within(card).findByText(/自动查找/)).toBeInTheDocument()
  await userEvent.click(within(card).getByRole('button', { name: '选择 codex.exe…' }))
  const result = await within(card).findByRole('status', { name: '选择结果' })
  expect(result).toHaveTextContent('可以使用')
  expect(result).toHaveTextContent('codex-cli 0.130.0')
  await userEvent.click(within(card).getByRole('button', { name: '保存并重启后台' }))
  expect(await within(card).findByRole('button', { name: '正在重启…' })).toBeDisabled()
  expect(calls.find((c) => c.cmd === 'desktop_save_codex')?.args).toEqual({ pick_id: 'pick-1' })
})

it('does not offer saving a program that cannot start, and ignores a cancelled dialog', async () => {
  server()
  let next: CodexPick | null = null
  shell({ desktop_info: () => info(), desktop_pick_codex: () => next })
  renderAt('/settings')
  const card = await screen.findByRole('region', { name: 'AI 服务位置' })
  await userEvent.click(await within(card).findByRole('button', { name: '选择 codex.exe…' }))
  expect(within(card).queryByRole('status', { name: '选择结果' })).not.toBeInTheDocument()
  next = {
    pick_id: 'pick-2',
    path: 'C:\\npm\\codex.exe',
    version: null,
    probe: 'failed',
    message: '已找到，但不能启动。请确认选择的是官方安装的 codex.exe。',
  }
  await userEvent.click(within(card).getByRole('button', { name: '选择 codex.exe…' }))
  const result = await within(card).findByRole('status', { name: '选择结果' })
  expect(result).toHaveTextContent('这个程序用不了')
  expect(result).toHaveTextContent('官方安装的 codex.exe')
  expect(within(card).queryByRole('button', { name: '保存并重启后台' })).not.toBeInTheDocument()
})

it('asks to pick again when the pick expired', async () => {
  server()
  shell({
    desktop_info: () => info(),
    desktop_pick_codex: () => okPick,
    desktop_save_codex: () => {
      throw { code: 'stale_pick', message: '请重新选择 codex.exe' }
    },
  })
  renderAt('/settings')
  const card = await screen.findByRole('region', { name: 'AI 服务位置' })
  await userEvent.click(await within(card).findByRole('button', { name: '选择 codex.exe…' }))
  await userEvent.click(await within(card).findByRole('button', { name: '保存并重启后台' }))
  expect(await within(card).findByText('请重新选择 codex.exe')).toBeInTheDocument()
  expect(within(card).queryByRole('status', { name: '选择结果' })).not.toBeInTheDocument()
})

it('restores automatic lookup for a configured path', async () => {
  server()
  const calls = shell({
    desktop_info: () => info('D:\\工具\\Codex\\codex.exe'),
    desktop_save_codex: () => ({ status: 'restarting' }),
  })
  renderAt('/settings')
  const card = await screen.findByRole('region', { name: 'AI 服务位置' })
  expect(await within(card).findByText('D:\\工具\\Codex\\codex.exe')).toBeInTheDocument()
  await userEvent.click(within(card).getByRole('button', { name: '恢复自动查找' }))
  await vi.waitFor(() =>
    expect(calls.find((c) => c.cmd === 'desktop_save_codex')?.args).toEqual({ auto: true }),
  )
})

it('lists desktop versions in About and opens the notices folder', async () => {
  server()
  const calls = shell({ desktop_info: () => info(), desktop_open_folder: () => null })
  renderAt('/settings')
  const about = await screen.findByRole('region', { name: '关于' })
  expect(await within(about).findByText('WebView2 157.0.4341.46')).toBeInTheDocument()
  expect(about).toHaveTextContent('Windows 11 (10.0.26200)')
  // 桌面程序与后台服务各一行
  expect(await within(about).findAllByText('v0.10.0', { selector: 'dd' })).toHaveLength(2)
  await userEvent.click(within(about).getByRole('button', { name: '第三方声明' }))
  await userEvent.click(within(about).getByRole('button', { name: '打开日志文件夹' }))
  expect(calls.filter((c) => c.cmd === 'desktop_open_folder').map((c) => c.args)).toEqual([
    { target: 'licenses' },
    { target: 'logs' },
  ])
  expect(document.body.textContent).not.toMatch(/undefined|null|tauri|nonce/i)
})

it('rechecks the AI service and offers restarting the backend in the desktop', async () => {
  const { posts } = server({
    ...idle,
    availability: {
      status: 'unavailable',
      reason: 'other',
      message: '已找到学习服务，但不能可靠启动此批处理安装。请选择原生 codex.exe。',
    },
  })
  const calls = shell({
    desktop_info: () => info(),
    desktop_restart_backend: () => ({ status: 'restarting' }),
  })
  renderAt('/settings')
  const guide = await screen.findByRole('region', { name: '使用说明' })
  const status = await within(guide).findByRole('status', { name: 'AI 服务状态' })
  expect(status).toHaveTextContent('已找到，但不能启动')
  expect(guide).toHaveTextContent('不要用 npm 安装的版本')
  await userEvent.click(within(guide).getByRole('button', { name: '重新检查' }))
  await vi.waitFor(() => expect(posts).toEqual(['/api/agent/connect']))
  await userEvent.click(within(guide).getByRole('button', { name: '重启后台' }))
  await vi.waitFor(() => expect(cmds(calls)).toContain('desktop_restart_backend'))
})

it('shows checking / not installed / not logged in in the onboarding', async () => {
  for (const [availability, title] of [
    [{ status: 'checking', reason: null, message: '' }, '检测中'],
    [{ status: 'unavailable', reason: 'not_installed', message: '' }, '未安装'],
    [{ status: 'unavailable', reason: 'not_logged_in', message: '' }, '未登录'],
  ] as const) {
    localStorage.clear()
    server({ ...idle, availability: { ...availability } })
    const { unmount } = render(
      <QueryClientProvider client={createQueryClient()}>
        <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/'] })} />
      </QueryClientProvider>,
    )
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: '下一步' }))
    expect(await within(dialog).findByRole('status', { name: 'AI 服务状态' })).toHaveTextContent(
      title,
    )
    if (title === '未安装') expect(dialog).toHaveTextContent('不建议用 npm 安装')
    // 浏览器里没有“重启后台”
    expect(within(dialog).queryByRole('button', { name: '重启后台' })).not.toBeInTheDocument()
    unmount()
    vi.unstubAllGlobals()
  }
})
