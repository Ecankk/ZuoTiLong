// 内嵌加载页：只显示外壳状态（boot://state 快照）并调用 boot_* 命令。
'use strict'

const { invoke } = window.__TAURI__.core
const { listen } = window.__TAURI__.event
const view = document.getElementById('view')

const ACTION_TEXT = {
  retry: '重试',
  choose_location: '重新选择位置',
  open_logs: '打开日志',
  quit: '退出',
}
const ACTION_CMD = {
  retry: 'boot_retry',
  choose_location: 'boot_choose_location',
  open_logs: 'boot_open_logs',
  quit: 'boot_quit',
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag)
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'class') node.className = value
    else if (key === 'onclick') node.addEventListener('click', value)
    else if (value === true) node.setAttribute(key, '')
    else if (value !== false && value != null) node.setAttribute(key, value)
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue
    node.append(child instanceof Node ? child : document.createTextNode(String(child)))
  }
  return node
}

function call(cmd) {
  return invoke(cmd).catch((e) => console.error(cmd, e))
}

function button(text, cmd, primary = false, disabled = false) {
  return el('button', { class: primary ? 'primary' : '', disabled, onclick: () => call(cmd) }, text)
}

function waiting(title, s) {
  return [el('div', { class: 'spinner', 'aria-hidden': 'true' }), el('h1', {}, title), el('p', {}, s.message || '请稍等…')]
}

function percent(progress) {
  if (!progress || !progress.total) return null
  return Math.min(100, Math.round((progress.completed / progress.total) * 100))
}

function chooseLocation(s) {
  const c = s.candidate
  const nodes = [el('h1', {}, s.relocating ? '选择新的数据位置' : '选择数据保存位置')]
  if (s.notice) nodes.push(el('p', { class: 'notice' }, s.notice))
  if (!s.relocating) {
    nodes.push(el('p', {}, '做题龙会把题库和你的学习记录保存在这台电脑上。一般用默认位置就好。'))
  }
  if (c) {
    const current = s.relocating && s.location && s.location.root === c.path
    const label = current ? '当前位置' : c.is_default ? '默认位置' : '选定的位置'
    nodes.push(
      el(
        'div',
        { class: c.usable ? 'path' : 'path bad' },
        el('strong', {}, label),
        el('div', {}, c.path),
        c.message ? el('small', {}, c.message) : null,
      ),
    )
  }
  nodes.push(
    el(
      'div',
      { class: 'actions' },
      button(c && c.kind === 'existing' ? '使用这里的记录' : '开始准备', 'boot_confirm_location', true, !(c && c.usable)),
      s.relocating ? button('取消，继续用原来的位置', 'boot_cancel') : null,
    ),
  )
  nodes.push(
    el(
      'details',
      { open: !c || !c.usable || !c.is_default },
      el('summary', {}, '更改位置'),
      el('p', {}, '可以选一个空文件夹，或以前的做题龙数据文件夹。不要选做题龙的安装文件夹。'),
      el(
        'div',
        { class: 'actions' },
        button('选择文件夹…', 'boot_choose_folder'),
        c && !c.is_default ? button('使用默认位置', 'boot_use_default') : null,
      ),
    ),
  )
  return nodes
}

function preparing(s) {
  const pct = percent(s.progress)
  return [
    el('h1', {}, '正在准备本地题库'),
    el('p', {}, s.message || '请稍等…'),
    el('div', { class: pct == null ? 'bar indeterminate' : 'bar' }, el('i', { style: pct == null ? null : `width:${pct}%` })),
    el('div', { class: 'meta' }, pct == null ? '第一次打开需要复制题库，可能要几分钟。' : `已完成 ${pct}%`),
    s.slow ? el('p', { class: 'notice' }, '仍在进行中，可以继续等待，也可以取消。') : null,
    el('div', { class: 'actions' }, button('取消', 'boot_cancel')),
  ]
}

function failure(s) {
  const e = s.error || { title: '出了点问题', message: '', actions: ['retry', 'quit'] }
  const actions = e.actions.map((a, i) => {
    const text = s.stage === 'crashed' && a === 'retry' ? '重新启动' : ACTION_TEXT[a]
    return button(text, ACTION_CMD[a], i === 0)
  })
  return [el('h1', {}, e.title), el('p', {}, e.message), el('div', { class: 'actions' }, actions)]
}

function render(s) {
  document.getElementById('version').textContent = s.app_version ? `版本 ${s.app_version}` : ''
  view.className = ['prepare_failed', 'start_failed', 'crashed'].includes(s.stage) ? 'card error' : 'card'
  let nodes
  switch (s.stage) {
    case 'choose_location':
      nodes = chooseLocation(s)
      break
    case 'preparing':
      nodes = preparing(s)
      break
    case 'prepare_failed':
    case 'start_failed':
    case 'crashed':
      nodes = failure(s)
      break
    case 'starting':
      nodes = waiting('正在打开做题龙', s)
      break
    case 'restarting':
      nodes = waiting('正在重新启动', s)
      break
    case 'stopping':
      nodes = waiting('请稍等', s)
      break
    case 'ready':
      nodes = waiting('马上就好', s)
      break
    default:
      nodes = waiting('正在打开做题龙', s)
  }
  view.replaceChildren(...nodes.filter(Boolean))
}

listen('boot://state', (event) => render(event.payload))
invoke('boot_state').then(render).catch(() => render({ stage: 'booting' }))
