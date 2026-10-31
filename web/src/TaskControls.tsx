import {useEffect,useState} from 'react'
import {postJson} from './api'
import {AgentActivity,AgentRequestCard} from './AgentPanel'
import type {AgentState,useAgentState} from './AgentPanel'

export function TaskControls({agent}:{agent:ReturnType<typeof useAgentState>}){
  const {state,reachable}=agent
  const [busy,setBusy]=useState(false),[error,setError]=useState('')
  const [preparation,setPreparation]=useState<{paper_id:string;status:string;pages_done?:number;pages_total?:number;questions?:number;message?:string;warnings?:string[]}[]>([])
  useEffect(()=>{let live=true;const load=()=>fetch('/api/preparation').then(r=>r.json()).then(v=>{if(live)setPreparation(v.items||[])}).catch(()=>{});load();const timer=setInterval(load,1200);return()=>{live=false;clearInterval(timer)}},[])
  const action=async(name:string,body:unknown={})=>{
    setBusy(true);setError('')
    try{agent.accept(await postJson<AgentState>(`/api/agent/${name}`,body));return true}
    catch(e){setError(e instanceof Error?e.message:'操作未完成');return false}
    finally{setBusy(false);agent.refresh()}
  }
  const preparationAction=async(id:string,operation:'pause'|'resume')=>{
    setBusy(true);setError('')
    try{await postJson(`/api/knowledge/preparation/${id}/action`,{operation});await agent.refresh()}
    catch(e){setError(e instanceof Error?e.message:'资料准备状态未更新')}
    finally{setBusy(false)}
  }
  return <section className="panel task-controls" aria-label="学习任务与连接">
    <div className="section-toolbar"><div><strong>{state?.external_control?state.control_reason==='released'?'网页已释放会话':'原会话暂不可用':state?.connected?'Codex 已连接':state?.status==='connecting'?'正在连接 Codex':'连接学习助手'}</strong>
      <p>{state?.model_settings?.model||'沿用本机 Codex 登录'}{state?.model_settings?.effort?` · ${state.model_settings.effort}`:''}</p></div>
      {!state?.connected&&<button className="primary" disabled={busy||!reachable||state?.status==='connecting'} onClick={()=>action('connect')}>{state?.session_id?'重新连接原会话':'连接 Codex'}</button>}
      {state?.connected&&['running','waiting_user'].includes(state.status)&&<button disabled={busy} onClick={()=>action('interrupt')}>停止当前阶段</button>}
      {state?.connected&&['failed','interrupted'].includes(state.status)&&<><button className="primary" disabled={busy} onClick={()=>action('retry')}>重试未完成阶段</button><button disabled={busy} onClick={()=>{if(confirm('确认结束这个已停止的任务？原卷、作答和已保存分析均保留。'))action('abandon',{confirmed:true})}}>结束本次任务</button></>}
    </div>
    <AgentActivity state={state} reachable={reachable}/>
    {state?.workflows?.filter(job=>['queued','blocked'].includes(job.status)||!state.active_request&&['failed','interrupted'].includes(job.status)).slice(0,3).map(job=><div className="notice workflow-notice" role="status" key={job.id}>
      <strong>{({review_practice:'核对练习解答',analyze_paper:'原卷分析',review_question:'原题复核',prepare_practice:'准备练习',grade_attempt:'批改作答',summarize_paper:'本卷总结',organize_knowledge:'整理考点证据',maintain_catalog:'统一考点整理',annotate_questions:'题目考点标注'} as Record<string,string>)[job.kind]||'资料处理'} · {job.status==='queued'?'已排入':'尚未完成'}</strong>
      <p>{job.paper_title?`${job.paper_title} · `:''}{job.error||(state.connected?'上一阶段结束后将继续，材料已保存。':'连接 Codex 后将继续，无需重新上传或提交。')}</p>
      {!state.active_request&&!state.external_control&&<div className="image-actions">{job.status!=='queued'&&<button disabled={busy||!!job.task_id&&!state.connected} onClick={()=>action('workflow-retry',{job_id:job.id})}>{job.recovery_required?'按保存材料继续本阶段':job.task_id?'核对并重试原阶段':'按当前材料重试本阶段'}</button>}{!job.task_id&&<button disabled={busy} onClick={()=>action('workflow-cancel',{job_id:job.id})}>取消等待，保留材料</button>}</div>}
    </div>)}
    {state?.knowledge_preparation?.filter(run=>['running','pausing','paused'].includes(run.status)).slice(0,2).map(run=><div className="notice" role="status" key={run.id}>
      <strong>{run.kind==='catalog'?'统一考点整理':'题目考点标注'}{run.status==='paused'?' · 已暂停':run.status==='pausing'?' · 本阶段完成后暂停':''}</strong>
      <p>已处理 {(run.counts.completed||0)+(run.counts.needs_review||0)} / {run.total} 条{run.counts.needs_review?` · ${run.counts.needs_review} 条待核`:''}</p>
      <progress style={{width:'100%'}} max={run.total||1} value={(run.counts.completed||0)+(run.counts.needs_review||0)} aria-label={run.kind==='catalog'?'考点整理进度':'题目标注进度'}/>
      {run.status==='needs_review'?<p>已保存可用结果；待核内容不会自动进入补强池。</p>:<button disabled={busy||run.status==='pausing'} onClick={()=>preparationAction(run.id,run.status==='paused'?'resume':'pause')}>{run.status==='paused'?'继续资料准备':run.status==='pausing'?'等待当前阶段保存':'暂停后续批次'}</button>}
    </div>)}
    {preparation.filter(p=>p.status==='running'||p.status==='failed'||p.status==='interrupted'||p.status==='needs_review').slice(0,1).map(p=><div className="notice" role="status" key={p.paper_id}><strong>{p.status==='running'?'正在识别原卷':p.status==='needs_review'?'切分存在疑点，交给 Agent 核对':'本地识别未完成'}</strong><p>{p.pages_total?`已读取 ${p.pages_done||0} / ${p.pages_total} 页`:'正在打开 PDF'}{p.questions!==undefined?` · 已初步定位 ${p.questions} 题`:''}</p>{p.status==='running'&&<div className="activity-track" role="progressbar" aria-label="本地识别进度"><span/></div>}{p.message&&<p>{p.message}</p>}{p.warnings?.map((warning,i)=><p key={i}>{warning}</p>)}</div>)}
    {state?.external_control&&<p className="notice">{state.control_reason==='released'?'可在 CLI 中调整模型；退出 CLI 后，重新连接原会话。':'请先结束其他客户端对原会话的占用，再重新连接；网页不会另建会话。'} Desktop 接管与释放尚未验证，请先使用 CLI。</p>}
    {state?.connection_notice&&<p className="muted">{state.connection_notice}</p>}
    {(error||state?.error||state?.workflow_error)&&<p role="alert" className="notice">{error||state?.error||state?.workflow_error}</p>}
    {state?.requests.map(item=><AgentRequestCard key={item.id} item={item} busy={busy} respond={body=>action('respond',{request_id:item.id,...body})}/>)}
  </section>
}
