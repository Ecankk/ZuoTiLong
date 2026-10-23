import {useEffect,useState} from 'react'
import {getBootstrap,postJson,restorePaper} from './api'
import type {Bootstrap,View,VisibleContext} from './types'
import {LearningWorkspace,EvidenceProfile,MathText} from './LearningWorkspace'
import {AgentPanel,useAgentState} from './AgentPanel'
import {LibraryBrowser} from './LibraryBrowser'
import {PaperList} from './PaperList'

const labels:Record<View,string>={papers:'试卷',paper:'试卷工作区',bank:'本地题库',profile:'个人画像',settings:'设置与记录'}
function route(){const q=new URLSearchParams(location.search);return {view:(['papers','paper','bank','profile','settings'].includes(q.get('view')||'')?q.get('view'):'papers') as View,paper:q.get('paper')||'',question:q.get('q')||'',probe:q.get('probe')||'',tab:q.get('tab')||'diagnosis'}}
export default function WorkspaceApp(){
  const agent=useAgentState(),[data,setData]=useState<Bootstrap|null>(null),[nav,setNav]=useState(route),[context,setContext]=useState<VisibleContext|null>(null),[open,setOpen]=useState(()=>innerWidth>1200),[error,setError]=useState('')
  const reload=async()=>{try{setData(await getBootstrap());setError('')}catch{setError('本地服务未连接，请重新运行启动脚本')}}
  useEffect(()=>{reload();const t=setInterval(reload,5000);const pop=()=>setNav(route()),discuss=()=>setOpen(true);addEventListener('popstate',pop);addEventListener('mathlens:discuss',discuss);return()=>{clearInterval(t);removeEventListener('popstate',pop);removeEventListener('mathlens:discuss',discuss)}},[])
  const navigate=(next:Partial<typeof nav>)=>{let value={...nav,...next};if(next.view&&next.view!=='paper')value={...value,paper:'',question:'',probe:'',tab:'diagnosis'};if(next.view&&next.view!==nav.view||next.paper&&next.paper!==nav.paper){setContext(null);window.scrollTo({top:0})}setNav(value);const q=new URLSearchParams({view:value.view});if(value.paper)q.set('paper',value.paper);if(value.question)q.set('q',value.question);if(value.probe)q.set('probe',value.probe);if(value.tab!=='diagnosis')q.set('tab',value.tab);const url=`?${q}`;if(url!==location.search)history.pushState({},'',url)}
  const openEvidence=(paper:string,question:string,tab='diagnosis',probe='')=>{setContext(null);navigate({view:'paper',paper,question,tab,probe})}
  const paper=data?.papers.find(p=>p.id===nav.paper)
  const visible:VisibleContext=nav.view==='paper'&&paper?(context?.paper_id===paper.id?context:{view:labels.paper,label:paper.title,paper_id:paper.id}):(nav.view==='bank'&&context?.view==='本地题库'||nav.view==='profile'&&context?.view==='个人画像')?context!:{view:labels[nav.view],label:labels[nav.view]}
  const key=JSON.stringify(visible)
  useEffect(()=>{const timer=setTimeout(()=>{fetch('/api/screen',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(visible)}).catch(()=>{})},250);return()=>clearTimeout(timer)},[key,visible])
  if(!data)return <div className="loading">{error||'正在加载本地项目…'}</div>
  const locked=!!agent.state?.input_locked||!agent.reachable
  return <div className={`shell ${open?'':'agent-collapsed'}`}><aside className="sidebar"><div className="brand"><span className="brand-mark">M</span><div><strong>MathLens</strong><small>数学{['','一','二','三'][data.preferences.study_type]} · 试卷诊断</small></div></div><div className="workspace">个人本地资料 · 单学习会话</div><nav>{(['papers','bank','profile','settings'] as View[]).map(v=><button key={v} className={`nav ${nav.view===v||v==='papers'&&nav.view==='paper'?'active':''}`} onClick={()=>navigate({view:v})}>{labels[v]}</button>)}</nav><div className="side-foot">v0.5.3 · 从试卷到原因</div></aside>
    <main className="main"><header className="topbar"><div><div className="eyebrow">{labels[nav.view]}</div><h1>{nav.view==='paper'?paper?.title||'试卷不存在':labels[nav.view]}</h1></div><button className="small-action" onClick={()=>navigate({view:'papers'})}>试卷列表</button></header>{error&&<p className="notice">{error}</p>}
    {nav.view==='papers'&&<PaperList data={data} locked={locked} reload={reload} select={id=>openEvidence(id,'')}/>}
    {nav.view==='paper'&&(paper?<>{paper.archived_at&&<section className="notice"><strong>这份试卷已归档</strong><p>历史材料可查看，学习写入暂停。恢复后重新纳入画像。</p><button disabled={locked} onClick={async()=>{if(window.confirm('确认恢复这份试卷，并将已有证据重新纳入当前画像？')){await restorePaper(paper.id);await reload()}}}>恢复这份试卷</button></section>}<LearningWorkspace key={paper.id} loop={data.loop} questions={data.questions} papers={data.papers} onReload={reload} paperId={paper.id} selectedId={nav.question} selectedProbeId={nav.probe} activeTab={nav.tab} onNavigate={(question,tab,probe='')=>navigate({question,tab,probe})} onContextChange={setContext} locked={locked||!!paper.archived_at}/></>:<p>请从试卷列表选择一份试卷。</p>)}
    {nav.view==='bank'&&<LibraryBrowser bank={data.bank} onContextChange={setContext}/>}
    {nav.view==='profile'&&<EvidenceProfile skills={data.loop.skills} papers={data.papers} questions={data.questions} probes={data.loop.probes} studyType={data.preferences.study_type} onReload={reload} onOpen={openEvidence} onContextChange={setContext} locked={locked}/>}
    {nav.view==='settings'&&<Settings data={data} locked={locked} reload={reload}/>}
    </main><aside id="agent-workspace" className="agent-rail" hidden={!open}><AgentPanel agent={agent} questions={data.questions} visibleContext={nav.view==='bank'&&context?.view==='本地题库'?context:visible} onReload={reload}/></aside><button className="primary agent-toggle" aria-controls="agent-workspace" aria-expanded={open} onClick={()=>setOpen(!open)}>{open?'收起 Agent':'打开 Agent'}</button></div>
}

function Settings({data,locked,reload}:{data:Bootstrap;locked:boolean;reload:()=>Promise<void>}){
  const [study,setStudy]=useState(data.preferences.study_type),[mask,setMask]=useState(data.preferences.mask_same_type),[reserved,setReserved]=useState(data.preferences.reserved.map(r=>`${r.math_type}:${r.year}`).join('\n')),[message,setMessage]=useState(''),[history,setHistory]=useState<{versions:any[];reports:any[]}|null>(null)
  const save=async()=>{try{await postJson('/api/preferences',{study_type:study,mask_same_type:mask,reserved:reserved.split(/\s+/).filter(Boolean).map(v=>{const [category,year]=v.split(':');return {math_type:Number(category),year}})});await reload();setMessage('已保存检验题显示规则；本地题库始终直接浏览')}catch(e){setMessage(String(e))}}
  return <>
    <section className="panel">
      <h2>针对性检验的题目显示</h2>
      <p>本地题库直接浏览。以下设置只决定试卷中针对性检验的题干是否隐藏。</p>
      <fieldset disabled={locked}>
        <label>当前备考类别<select aria-label="正在学习的数学类别" value={study} onChange={e=>setStudy(Number(e.target.value))}>{[1,2,3].map(n=><option value={n} key={n}>数学{['','一','二','三'][n]}</option>)}</select></label>
        <label><input type="checkbox" aria-label="隐藏同类别检验题" checked={mask} onChange={e=>setMask(e.target.checked)}/>隐藏同类别检验题，点击确认后查看</label>
        <p>{mask?`数学${['','一','二','三'][study]}检验题隐藏题干，其余类别直接显示。`:'所有类别的检验题均直接显示。'}解析仍由你选择查看。</p>
        <details><summary>额外预留整卷（可选）</summary><label>不用于 Agent 选题，每行“类别:年份”，例如 1:2025<textarea aria-label="预留整卷" value={reserved} onChange={e=>setReserved(e.target.value)}/></label></details>
        <button className="primary" onClick={save}>保存检验显示设置</button>
      </fieldset>
      <p role="status">{message}</p>
    </section>
    <section className="panel"><h2>本地备份与修订</h2><p>备份包含个人原卷、照片、画像和记忆，请自行保管。恢复使用独立目录，不覆盖当前资料。</p><button disabled={locked} onClick={async()=>{try{const result=await postJson<{path:string}>('/api/maintenance/backup',{});setMessage('备份已保存：'+result.path)}catch(e){setMessage(String(e))}}}>创建本地备份</button><button disabled={locked} onClick={async()=>{try{const result=await postJson<{moved:number}>('/api/maintenance/cleanup',{});setMessage(`已将 ${result.moved} 个无引用旧上传移入可恢复目录`)}catch(e){setMessage(String(e))}}}>整理无引用旧照片</button><button onClick={async()=>setHistory(await (await fetch('/api/versions')).json())}>查看修订历史</button>{history&&<><h3>作答与检验修订</h3>{history.versions.map(v=><details key={v.id}><summary>{v.created_at} · {v.kind} · {v.reason}</summary><pre>{v.payload}</pre></details>)}<h3>诊断报告版本</h3>{history.reports.map(r=><p key={r.id}>{r.created_at} · {r.paper_id} <button disabled={locked} onClick={async()=>{const reason=prompt('恢复此报告的原因？');if(reason){await postJson(`/api/reports/${r.id}/restore`,{reason});await reload()}}}>恢复为当前报告</button></p>)}</>}</section>
  </>
}
