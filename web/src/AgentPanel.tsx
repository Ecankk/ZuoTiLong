import { useEffect, useRef, useState } from 'react'
import { postJson } from './api'
import { MathText } from './LearningWorkspace'
import type { Paper, Question, VisibleContext } from './types'

type AgentRequest = { id: string; method: string; params: { command?: string; reason?: string; questions?: { id: string; question: string; options?: { label: string; description: string }[]; isSecret?: boolean }[]; [key: string]: unknown } }
export type AgentState = {
  revision: number; connected: boolean; can_submit: boolean; input_locked: boolean; session_id?: string;
  status: string; activity: string; error?: string; active_request?: string; requests: AgentRequest[];
  turns: { request_id: string; text: string; status: string; context: { paper_id?: string; question_id?: string }; messages: { id: string; text: string; phase?: string; complete: boolean }[] }[]
}

export function useAgentState() {
  const [state, setState] = useState<AgentState | null>(null)
  const [reachable, setReachable] = useState(false)
  const polling = useRef(false)
  const refresh = async () => {
    if (polling.current) return
    polling.current = true
    try {
      const response = await fetch('/api/agent/state', { signal: AbortSignal.timeout(10000) })
      if (!response.ok) throw new Error('连接不可用')
      const next: AgentState = await response.json()
      setState(old => !old || next.revision >= old.revision ? next : old)
      setReachable(true)
    } catch { setReachable(false) }
    finally { polling.current = false }
  }
  useEffect(() => { refresh(); const timer = setInterval(refresh, 1000); window.addEventListener('mathlens:agent-refresh', refresh); return () => { clearInterval(timer); window.removeEventListener('mathlens:agent-refresh', refresh) } }, [])
  return { state, reachable, refresh, accept: (next: AgentState) => setState(old => !old || next.revision >= old.revision ? next : old) }
}

export function AgentPanel({ agent, papers, questions, visibleContext, onReload }: {
  agent: ReturnType<typeof useAgentState>; papers: Paper[]; questions: Question[]; visibleContext: VisibleContext; onReload: () => Promise<void>
}) {
  const { state, reachable } = agent
  const [text, setText] = useState('')
  const [paperId, setPaperId] = useState('')
  const [questionId, setQuestionId] = useState('')
  const [followPage, setFollowPage] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<{ id: string; text: string; context: string } | null>(null)
  const transcript = useRef<HTMLDivElement>(null)
  const followLatest = useRef(true)
  const restoredContext = useRef(false)
  const lastCompleted = useRef('')
  const last = state?.turns.at(-1)
  useEffect(() => {
    if (state && !restoredContext.current) {
      restoredContext.current = true
      if (last) { setPaperId(last.context.paper_id || ''); setQuestionId(last.context.question_id || '') }
    }
  }, [state])
  useEffect(() => {
    if (last?.status === 'completed' && lastCompleted.current !== last.request_id) {
      lastCompleted.current = last.request_id; onReload()
    }
  }, [last?.status, last?.request_id])
  useEffect(() => {
    const node = transcript.current
    if (node && followLatest.current) node.scrollTop = node.scrollHeight
  }, [state?.revision])
  const action = async (name: string, body: unknown = {}) => {
    setBusy(true); setError('')
    try { const next = await postJson<AgentState>(`/api/agent/${name}`, body); agent.accept(next); return true }
    catch (e) { setError(e instanceof Error ? e.message : '请求失败'); return false }
    finally { setBusy(false); agent.refresh() }
  }
  const send = async () => {
    followLatest.current = true
    const attachedPaper = followPage ? visibleContext.paper_id : paperId
    const attachedQuestion = followPage ? visibleContext.question_id : questionId
    const context = { screen: {...visibleContext, label: visibleContext.label.slice(0,2000)},
      ...(attachedPaper ? { paper_id: attachedPaper } : {}), ...(attachedQuestion ? { question_id: attachedQuestion } : {}) }
    const content = text.trim(), contextKey = JSON.stringify(context)
    if (!request.current || request.current.text !== content || request.current.context !== contextKey)
      request.current = { id: crypto.randomUUID(), text: content, context: contextKey }
    if (await action('send', { text: content, request_id: request.current.id, context })) { setText(''); request.current = null }
  }
  const disabled = busy || !reachable || !state?.can_submit
  const labels: Record<string, string> = { disconnected: '未连接', connecting: '连接中', idle: '可以继续', running: '处理中 · 输入已锁定', waiting_user: '等待你的确认', failed: '本轮未完成', interrupted: '本轮已中断' }
  return <section className="panel agent-panel" aria-label="与 Codex 讨论">
    <div className="panel-head"><div><div className="eyebrow">同一个 Codex 会话 · 本地保存</div><h2>与 Codex 讨论</h2></div><span className="status pending" role="status">{reachable ? labels[state?.status || 'disconnected'] : '正在确认连接'}</span></div>
    <p className="muted">发送时附上当前页面与题目，等待完整反馈后继续。</p>
    <div className="agent-visible-context"><span>当前正在看</span><strong title={visibleContext.label}><MathText text={visibleContext.label}/></strong><small>{visibleContext.view}{visibleContext.section ? ` · ${visibleContext.section}` : ''}</small></div>
    {state?.session_id && <details><summary>当前会话</summary><code>{state.session_id}</code><p>重启后继续使用此会话。请在这里提交学习消息，避免同时在 CLI/Desktop 向该会话发消息。</p></details>}
    {!state?.connected && <button className="primary" disabled={busy || state?.status === 'connecting' || !reachable} onClick={() => action('connect')}>{state?.session_id ? '重新连接原会话' : '连接 Codex'}</button>}
    {!!state?.turns.length && <div className="agent-transcript" ref={transcript} aria-live="polite" onScroll={e => { const n=e.currentTarget; followLatest.current=n.scrollHeight-n.scrollTop-n.clientHeight<100 }}>{state.turns.map(turn => <article className="agent-turn" key={turn.request_id}>
      <div className="agent-user"><small>你 {turn.context.question_id ? `· 第${questions.find(q => q.id === turn.context.question_id)?.number || '?'}题` : ''}</small><MathText text={turn.text}/></div>
      {turn.messages.map(message => <div key={message.id} className={`agent-answer ${message.phase === 'commentary' ? 'agent-progress' : ''}`}><small>{message.phase === 'commentary' ? '处理进展' : 'Codex'}</small><MathText text={message.text}/></div>)}
      {turn.status !== 'completed' && <small className="muted">{turn.request_id === state.active_request ? state.activity : '此前未完成的记录'}</small>}
    </article>)}</div>}
    {(error || state?.error) && <p role="alert" className="notice">{error || state?.error}</p>}
    {state?.requests.map(item => <AgentRequestCard key={item.id} item={item} busy={busy} respond={body => action('respond', { request_id: item.id, ...body })}/>)}
    {state?.input_locked && <div className="agent-controls"><strong>等待 Agent 完整反馈，当前不能输入下一步内容。</strong>
      {state.connected && ['running', 'waiting_user'].includes(state.status) && <button className="small-action" disabled={busy} onClick={() => action('interrupt')}>停止本轮</button>}
      {state.connected && ['failed', 'interrupted'].includes(state.status) && <button className="primary" disabled={busy} onClick={() => action('retry')}>重试原请求</button>}
    </div>}
    <fieldset className="agent-composer" disabled={disabled}>
      <label className="check-label"><input type="checkbox" checked={followPage} onChange={e => setFollowPage(e.target.checked)}/>跟随当前题目，附上原卷区域</label>
      {!followPage && <div className="agent-context"><label>关联试卷<select aria-label="关联试卷" value={paperId} onChange={e => { setPaperId(e.target.value); setQuestionId('') }}><option value="">整体讨论</option>{papers.filter(p => p.source_name).map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select></label>
        <label>关联题目<select aria-label="关联题目" value={questionId} onChange={e => setQuestionId(e.target.value)}><option value="">整张试卷</option>{questions.filter(q => q.paper_id === paperId).sort((a,b) => Number(a.number)-Number(b.number)).map(q => <option key={q.id} value={q.id}>第 {q.number} 题</option>)}</select></label></div>}
      <textarea aria-label="给 Codex 的内容" value={text} onChange={e => setText(e.target.value)} placeholder="例如：我知道这里要换元，但不确定积分上下限为什么这样变。" maxLength={16000}/>
      <button className="primary" disabled={disabled || !text.trim()} onClick={send}>{busy ? '正在提交…' : '发送并等待反馈'}</button>
    </fieldset>
  </section>
}

function AgentRequestCard({ item, busy, respond }: { item: AgentRequest; busy: boolean; respond: (body: Record<string, unknown>) => Promise<boolean> }) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const questions = item.params.questions
  return <div className="agent-request"><h3>{questions ? 'Agent 需要补充说明' : 'Codex 请求本次授权'}</h3>
    {questions ? <>{questions.map(q => <label key={q.id}>{q.question}{q.options?.map(option => <button className="small-action" disabled={busy} type="button" key={option.label} onClick={() => setAnswers(a => ({ ...a, [q.id]: option.label }))}>{option.label}</button>)}<input type={q.isSecret ? 'password' : 'text'} aria-label={q.question} value={answers[q.id] || ''} onChange={e => setAnswers(a => ({ ...a, [q.id]: e.target.value }))}/></label>)}<button className="primary" disabled={busy || questions.some(q => !answers[q.id]?.trim())} onClick={() => respond({ answers })}>提交这次补充</button></> : <>
      <p>{item.params.reason || '此操作需要你确认后，Agent 才能继续。'}</p><pre>{item.params.command || JSON.stringify(item.params, null, 2)}</pre>
      <button className="primary" disabled={busy} onClick={() => respond({ decision: 'accept' })}>仅允许本次</button> <button className="small-action" disabled={busy} onClick={() => respond({ decision: 'decline' })}>拒绝</button>
    </>}
  </div>
}
