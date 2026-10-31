import { useEffect, useRef, useState } from 'react'
import { postJson } from './api'
import { MathText } from './LearningWorkspace'
import type { Preferences, Question, VisibleContext } from './types'
import {AgentPrompt} from './AgentPrompt'
import { useAnswerImages, AnswerImagePicker, SubmittedImages } from './AnswerImages'
import {useDraft} from './drafts'
import {mergeAgentState} from './agent-state'

type AgentRequest = { id: string; method: string; params: { command?: string; reason?: string; questions?: { id: string; question: string; options?: { label: string; description: string }[]; isSecret?: boolean }[]; [key: string]: unknown } }
export type AgentState = {
  revision: number; connected: boolean; can_submit: boolean; input_locked: boolean; session_id?: string;
  snapshot_epoch?:string; snapshot_sequence?:number;
  status: string; activity: string; error?: string; connection_notice?: string; active_request?: string; requests: AgentRequest[];
  learning_tools_version?:number;
  updated_at?:string;
  external_control?:boolean;
  control_reason?:'released'|'conflict';
  workflow_error?:string;
  workflows?:{id:string;paper_id:string|null;paper_title:string|null;kind:string;attempt_id?:string;status:string;task_id?:string;error?:string;recovery_required?:number}[];
  knowledge_preparation?:{id:string;kind:string;status:string;total:number;counts:Record<string,number>}[];
  model_settings?:{model:string|null;effort:string|null;source:string;observed_at:string};
  turns: { request_id: string; text: string; status: string; created_at?:string; started_at?:string; finished_at?:string; image_ids?:string[]; context: { paper_id?: string; question_id?: string }; messages: { id: string; text: string; phase?: string; complete: boolean }[] }[]
}

export function AgentActivity({state,reachable=true}:{state:AgentState|null;reachable?:boolean}){
  const [clock,setClock]=useState(Date.now())
  const active=state?.turns.find(t=>t.request_id===state.active_request)
  useEffect(()=>{if(!active)return;const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer)},[active?.request_id])
  if(!state?.input_locked||state.external_control)return null
  const start=Date.parse(active?.started_at||active?.created_at||''),last=Date.parse(state.updated_at||''),finished=Date.parse(active?.finished_at||'')
  const seconds=Number.isFinite(start)?Math.max(0,Math.floor(((Number.isFinite(finished)?finished:clock)-start)/1000)):0
  const idle=Number.isFinite(last)?Math.max(0,Math.floor((clock-last)/1000)):0
  const waiting=state.status==='waiting_user',failed=['disconnected','failed','interrupted'].includes(state.status)
  const title=!reachable?'暂时无法确认本地服务状态':waiting?'等待你的授权或补充':failed?'本轮尚未完成':state.status==='connecting'?'正在连接 Codex':'Agent 正在处理'
  return <div className={`agent-activity ${waiting||failed||!reachable?'paused':''}`} role="status">
    <div className="activity-heading"><span className="activity-dot" aria-hidden="true"/><strong>{title}</strong>{active&&<small>已用 {Math.floor(seconds/60)}分{seconds%60}秒</small>}</div>
    <p>{state.activity}</p>
    {!waiting&&!failed&&reachable&&<div className="activity-track" role="progressbar" aria-label="Agent 处理中，进度无法按百分比估算"><span/></div>}
    {idle>=120&&!waiting&&!failed&&<small>已有 {Math.floor(idle/60)} 分钟未收到新活动，仍在等待 Codex。可在任务状态中停止本轮。</small>}
    {(waiting||failed||!reachable)&&<small>材料和已保存结果保留；请在任务状态中处理当前阶段后继续。</small>}
  </div>
}

export function useAgentState() {
  const [state, setState] = useState<AgentState | null>(null)
  const [reachable, setReachable] = useState(false)
  const polling = useRef(false)
  const issued=useRef(0),accepted=useRef(0)
  const accept=(next:AgentState)=>{
    accepted.current=++issued.current
    setState(old=>mergeAgentState(old,next))
    setReachable(true)
  }
  const refresh = async () => {
    if (polling.current) return
    polling.current = true
    const request=++issued.current
    try {
      const response = await fetch('/api/agent/state', { signal: AbortSignal.timeout(10000) })
      if (!response.ok) throw new Error('连接不可用')
      const next: AgentState = await response.json()
      if(request>=accepted.current){
        accepted.current=request
        setState(old=>mergeAgentState(old,next))
        setReachable(true)
      }
    } catch { if(request>=accepted.current)setReachable(false) }
    finally { polling.current = false }
  }
  useEffect(() => { refresh(); const timer = setInterval(refresh, 1000); window.addEventListener('mathlens:agent-refresh', refresh); return () => { clearInterval(timer); window.removeEventListener('mathlens:agent-refresh', refresh) } }, [])
  return { state, reachable, refresh, accept }
}

export function AgentPanel({ agent, questions, visibleContext, onReload, preferences }: {
  agent: ReturnType<typeof useAgentState>; questions: Question[]; visibleContext: VisibleContext; onReload: () => Promise<void>; preferences:Preferences
}) {
  const { state, reachable } = agent
  const [text, setText] = useDraft('agent:text','')
  const photos = useAnswerImages()
  const [busy, setBusy] = useState(false)
  const [promptSaving,setPromptSaving]=useState(false)
  const [error, setError] = useState('')
  const request = useRef<{ id: string; text: string; context: string } | null>(null)
  const transcript = useRef<HTMLDivElement>(null)
  const followLatest = useRef(true)
  const lastCompleted = useRef('')
  const last = state?.turns.at(-1)
  useEffect(()=>{const discuss=(event:Event)=>setText(old=>(old?old+'\n\n':'')+(event as CustomEvent<string>).detail);window.addEventListener('mathlens:discuss',discuss);return()=>window.removeEventListener('mathlens:discuss',discuss)},[])
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
    const attachedPaper = visibleContext.paper_id
    const attachedQuestion = visibleContext.question_id
    const context = { screen: {...visibleContext, label: visibleContext.label.slice(0,2000)},
      ...(attachedPaper ? { paper_id: attachedPaper } : {}), ...(attachedQuestion ? { question_id: attachedQuestion } : {}) }
    const image_ids=photos.images.map(image=>image.id)
    const content = text.trim(), contextKey = JSON.stringify({context,image_ids})
    if (!request.current || request.current.text !== content || request.current.context !== contextKey)
      request.current = { id: crypto.randomUUID(), text: content, context: contextKey }
    if (await action('send', { text: content, request_id: request.current.id, context, image_ids })) { setText(''); photos.clear();request.current = null }
  }
  const disabled = busy || promptSaving || photos.busy || !reachable || !state?.can_submit
  const labels: Record<string, string> = { disconnected: '未连接', connecting: '连接中', idle: '可以继续', running: '处理中 · 输入已锁定', waiting_user: '等待你的确认', failed: '本轮未完成', interrupted: '本轮已中断' }
  return <section className="panel agent-panel" aria-label="与 Codex 讨论">
    <div className="panel-head"><div><div className="eyebrow">本机 Codex 登录 · 固定学习会话</div><h2>与 Codex 讨论</h2></div><span className="status pending" role="status">{reachable ? labels[state?.status || 'disconnected'] : '正在确认连接'}</span></div>
    <AgentPrompt preferences={preferences} locked={busy||!reachable||!!state?.input_locked} onReload={onReload} onSaving={setPromptSaving}/>
    <div className="agent-model"><div><small>{state?.connected?'Codex 会话配置':'上次确认的会话配置'}</small><strong>{state?.model_settings?.model||'连接后确认'}{state?.model_settings?.effort?` · ${state.model_settings.effort}`:''}</strong></div>
      {state?.connected&&!state.input_locked&&<button className="small-action" disabled={busy||!reachable} onClick={()=>action('release')}>去 Codex 切换模型</button>}
    </div>
    {state?.external_control&&<div className="notice" role="status"><strong>已释放原会话，等待返回</strong><p>在 Codex Desktop/CLI 调整同一会话的模型。结束对应 CLI（/quit）或释放 Desktop 会话后，再点“重新连接原会话”。网页将读回保存的设置。</p><code>codex resume {state.session_id}</code><p>CLI 内使用 /model。仅修改菜单未必已保存；以网页重连后的配置为准，仍被占用时不会新建会话。</p></div>}
    <p className="muted">发送时附上当前页面与题目。解释、提问和结果都在这里反馈，处理中只显示状态。</p>
    <div className="agent-visible-context"><span>当前正在看</span><strong title={visibleContext.label}><MathText text={visibleContext.label}/></strong><small>{visibleContext.view}{visibleContext.section ? ` · ${visibleContext.section}` : ''}</small></div>
    {visibleContext.question_id&&<details><summary>当前原卷缩略图</summary><img className="evidence-image" src={`/api/questions/${visibleContext.question_id}/evidence`} alt="当前题目原卷区域"/><p>图片为原卷证据；OCR 仅作定位草稿。</p></details>}
    {state?.session_id && <details><summary>当前会话</summary><code>{state.session_id}</code><p>切换试卷、刷新和重启均复用此会话。切换模型前先由网页释放会话；学习内容继续在网页提交。</p></details>}
    {state?.connection_notice&&<p className="notice" role="status">{state.connection_notice}</p>}
    <AgentActivity state={state} reachable={reachable}/>
    {!state?.connected && <button className="primary" disabled={busy || state?.status === 'connecting' || !reachable} onClick={() => action('connect')}>{state?.session_id ? '重新连接原会话' : '连接 Codex'}</button>}
    {state?.session_id&&state.learning_tools_version!==1&&!state.input_locked&&<button className="small-action" disabled={busy} onClick={()=>{if(window.confirm('启用支持内置学习工具的新会话？旧消息和个人资料仍保留，新的对话从本地学习记录恢复。'))action('upgrade-tools',{confirmed:true})}}>启用内置学习工具…</button>}
    {!!state?.turns.length && <div className="agent-transcript" ref={transcript} aria-live="polite" onScroll={e => { const n=e.currentTarget; followLatest.current=n.scrollHeight-n.scrollTop-n.clientHeight<100 }}>{state.turns.map(turn => <article className="agent-turn" key={turn.request_id}>
      <div className="agent-user"><small>你 {turn.context.question_id ? `· 第${questions.find(q => q.id === turn.context.question_id)?.number || '?'}题` : ''}</small><MathText text={turn.text}/><SubmittedImages ids={turn.image_ids}/></div>
      {turn.messages.filter(m=>m.phase==='final_answer'||(!m.phase&&m.complete)).map(message => <div key={message.id} className="agent-answer"><small>Codex</small><MathText text={message.text}/></div>)}
      {turn.status !== 'completed' && <small className="muted">{turn.request_id === state.active_request ? state.activity : '此前未完成的记录'}</small>}
    </article>)}</div>}
    {(error || state?.error) && <p role="alert" className="notice">{error || state?.error}</p>}
    {state?.requests.map(item => <AgentRequestCard key={item.id} item={item} busy={busy} respond={body => action('respond', { request_id: item.id, ...body })}/>)}
    {state?.input_locked&&!state.external_control && <div className="agent-controls"><strong>等待 Agent 完整反馈，当前不能输入下一步内容。</strong>
      {state.connected && ['running', 'waiting_user'].includes(state.status) && <button className="small-action" disabled={busy} onClick={() => action('interrupt')}>停止本轮</button>}
      {state.connected && ['failed', 'interrupted'].includes(state.status) && <button className="primary" disabled={busy} onClick={() => action('retry')}>重试原请求</button>}
      {state.connected&&['failed','interrupted'].includes(state.status)&&<button className="small-action" disabled={busy} onClick={()=>{if(window.confirm('确认放弃已停止的本轮？原输入和作答仍保留，不会伪造完成。'))action('abandon',{confirmed:true})}}>放弃本轮并保留记录</button>}
    </div>}
    <fieldset className="agent-composer" disabled={disabled}>
      <textarea aria-label="给 Codex 的内容" value={text} onChange={e => setText(e.target.value)} onPaste={e=>{if(e.clipboardData.files.length){e.preventDefault();photos.addFiles(Array.from(e.clipboardData.files))}}} placeholder="写下思路，或上传手写作答照片；也可直接粘贴截图。" maxLength={16000}/>
      <AnswerImagePicker draft={photos} disabled={disabled}/>
      <button className="primary" disabled={disabled || (!text.trim()&&!photos.images.length)} onClick={send}>{busy ? '正在提交…' : '发送并等待反馈'}</button>
    </fieldset>
  </section>
}

export function AgentRequestCard({ item, busy, respond }: { item: AgentRequest; busy: boolean; respond: (body: Record<string, unknown>) => Promise<boolean> }) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const questions = item.params.questions
  return <div className="agent-request"><h3>{questions ? 'Agent 需要补充说明' : 'Codex 请求本次授权'}</h3>
    {questions ? <>{questions.map(q => <label key={q.id}>{q.question}{q.options?.map(option => <button className="small-action" disabled={busy} type="button" key={option.label} onClick={() => setAnswers(a => ({ ...a, [q.id]: option.label }))}>{option.label}</button>)}<input type={q.isSecret ? 'password' : 'text'} aria-label={q.question} value={answers[q.id] || ''} onChange={e => setAnswers(a => ({ ...a, [q.id]: e.target.value }))}/></label>)}<button className="primary" disabled={busy || questions.some(q => !answers[q.id]?.trim())} onClick={() => respond({ answers })}>提交这次补充</button></> : <>
      <p>{item.params.reason || '此操作需要你确认后，Agent 才能继续。'}</p>{item.params.command&&<pre>{item.params.command}</pre>}
      <button className="primary" disabled={busy} onClick={() => respond({ decision: 'accept' })}>仅允许本次</button> <button className="small-action" disabled={busy} onClick={() => respond({ decision: 'decline' })}>拒绝</button>
    </>}
  </div>
}
