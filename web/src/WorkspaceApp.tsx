import {useEffect,useState} from 'react'
import {getBootstrap,postJson,restorePaper} from './api'
import type {Bootstrap,View} from './types'
import {LearningWorkspace,EvidenceProfile} from './LearningWorkspace'
import {useAgentState} from './AgentPanel'
import {AgentPrompt} from './AgentPrompt'
import {TaskControls} from './TaskControls'
import {LibraryBrowser} from './LibraryBrowser'
import {PaperList} from './PaperList'
import {CatalogPackages} from './CatalogPackages'
import {QuestionIndexPackages} from './QuestionIndexPackages'

const labels:Record<View,string>={papers:'试卷',paper:'试卷工作区',bank:'本地题库',knowledge:'考点树',profile:'个人画像',settings:'设置与记录'}
function route(){const q=new URLSearchParams(location.search);return {view:(['papers','paper','bank','knowledge','profile','settings'].includes(q.get('view')||'')?q.get('view'):'papers') as View,paper:q.get('paper')||'',question:q.get('q')||'',probe:q.get('probe')||'',goal:q.get('goal')||'',topic:q.get('topic')||'',tab:q.get('tab')||'diagnosis',bankId:q.get('bank_id')||'',questionView:(['bank','completed'].includes(q.get('question_view')||'')?q.get('question_view'):'') as ''|'bank'|'completed',offset:Math.max(0,Number(q.get('offset'))||0),category:q.get('math_type')||'',year:q.get('year')||''}}

const ignoreContext=()=>{}
export default function WorkspaceApp(){
  const agent=useAgentState(),[data,setData]=useState<Bootstrap|null>(null),[nav,setNav]=useState(route),[error,setError]=useState('')
  const reload=async()=>{try{setData(await getBootstrap());setError('')}catch{setError('本地服务未连接，请重新运行启动脚本')}}
  useEffect(()=>{reload();const timer=setInterval(reload,3000);const pop=()=>setNav(route());addEventListener('popstate',pop);return()=>{clearInterval(timer);removeEventListener('popstate',pop)}},[])
  const navigate=(next:Partial<typeof nav>)=>{
    let value={...nav,...next}
    if(next.view&&next.view!=='paper')value={...value,paper:'',question:'',probe:'',goal:'',tab:'diagnosis'}
    if(next.view&&next.view!==nav.view&&next.offset===undefined)value.offset=0
    if(value.view!=='profile'&&value.view!=='knowledge'&&value.view!=='bank'&&(value.view!=='paper'||value.tab!=='profile'))value.topic=''
    if(value.view!=='bank')value.bankId=''
    setNav(value)
    const q=new URLSearchParams({view:value.view})
    for(const [key,text] of Object.entries({paper:value.paper,q:value.question,probe:value.probe,goal:value.goal,topic:value.topic,bank_id:value.bankId,question_view:value.questionView,offset:value.offset?String(value.offset):'',math_type:value.view==='bank'?value.category:'',year:value.view==='bank'?value.year:''}))if(text)q.set(key,text)
    if(value.tab!=='diagnosis')q.set('tab',value.tab)
    if(`?${q}`!==location.search)history.pushState({},'',`?${q}`)
  }
  const openEvidence=(paper:string,question:string,tab='diagnosis',probe='')=>navigate({view:'paper',paper,question,tab,probe,goal:'',topic:''})
  const paper=data?.papers.find(p=>p.id===nav.paper)
  if(!data)return <div className="loading">{error||'正在加载本地项目…'}</div>
  const locked=!!agent.state?.input_locked||!agent.reachable
  return <div className="shell agent-collapsed"><aside className="sidebar"><div className="brand"><span className="brand-mark">M</span><div><strong>MathLens</strong><small>数学{['','一','二','三'][data.preferences.study_type]} · 试卷复习</small></div></div><div className="workspace">个人本地资料</div><nav>{(['papers','bank','knowledge','profile','settings'] as View[]).map(v=><button key={v} className={`nav ${nav.view===v||v==='papers'&&nav.view==='paper'?'active':''}`} onClick={()=>navigate({view:v})}>{labels[v]}</button>)}</nav><div className="side-foot">原卷 · 少量练习 · 反馈</div></aside>
    <main className="main"><header className="topbar"><div><div className="eyebrow">{labels[nav.view]}</div><h1>{nav.view==='paper'?paper?.title||'试卷不存在':labels[nav.view]}</h1></div><button onClick={()=>navigate({view:'papers'})}>试卷列表</button></header>
    {error&&<p className="notice">{error}</p>}<TaskControls agent={agent}/>
    {nav.view==='papers'&&<PaperList data={data} locked={locked} reload={reload} select={id=>openEvidence(id,'')}/>}
    {nav.view==='paper'&&(paper?<>{paper.archived_at&&<section className="notice"><p>这份试卷已归档，历史材料仍可查看。</p><button disabled={locked} onClick={async()=>{if(confirm('确认恢复这份试卷，并重新纳入当前画像？')){await restorePaper(paper.id);await reload()}}}>恢复试卷</button></section>}<LearningWorkspace key={paper.id} loop={data.loop} questions={data.questions} papers={data.papers} onReload={reload} paperId={paper.id} selectedId={nav.question} selectedProbeId={nav.probe} selectedGoalId={nav.goal} selectedKnowledgeId={nav.topic} onSelectKnowledge={topic=>navigate({topic})} onOpenRelated={p=>openEvidence(p.paper_id,p.question_id,'probes',p.id)} activeTab={nav.tab} onNavigate={(question,tab,probe='',goal='')=>navigate({question,tab,probe,goal})} onContextChange={ignoreContext} locked={locked||!!paper.archived_at}/></>:<p>请从试卷列表选择一份试卷。</p>)}
    {nav.view==='bank'&&<LibraryBrowser bank={data.bank} bankId={nav.bankId} topicId={nav.topic} category={nav.category} year={nav.year} offset={nav.offset} onNavigate={navigate} onTopic={topic=>navigate({view:'knowledge',topic,questionView:'bank',offset:0})} onContextChange={ignoreContext}/>}
    {(nav.view==='knowledge'||nav.view==='profile')&&<EvidenceProfile key={nav.view} catalogOnly={nav.view==='knowledge'} selectedId={nav.topic} onSelect={topic=>navigate({topic,offset:0})} questionView={nav.questionView} questionOffset={nav.offset} onQuestionView={questionView=>navigate({questionView,offset:0})} onQuestionOffset={offset=>navigate({offset})} onOpenBank={bankId=>navigate({view:'bank',bankId,topic:nav.topic,offset:0})} skills={data.loop.knowledge||[]} pendingSources={data.loop.knowledge_index?.pending_sources} papers={data.papers} questions={data.questions} probes={data.loop.probes} studyType={data.preferences.study_type} onReload={reload} onOpen={openEvidence} onContextChange={ignoreContext} locked={locked}/>}
    {nav.view==='settings'&&<Settings data={data} locked={locked} reload={reload} agent={agent}/>}
    </main></div>
}

function Settings({data,locked,reload,agent}:{data:Bootstrap;locked:boolean;reload:()=>Promise<void>;agent:ReturnType<typeof useAgentState>}){
  const [study,setStudy]=useState(data.preferences.study_type),[mask,setMask]=useState(data.preferences.mask_same_type),[reserved,setReserved]=useState(data.preferences.reserved.map(r=>`${r.math_type}:${r.year}`).join('\n')),[message,setMessage]=useState(''),[history,setHistory]=useState<{versions:any[];reports:any[]}|null>(null)
  const save=async()=>{try{await postJson('/api/preferences',{study_type:study,mask_same_type:mask,reserved:reserved.split(/\s+/).filter(Boolean).map(v=>{const [category,year]=v.split(':');return {math_type:Number(category),year}})});await reload();setMessage('已保存检验题显示规则；本地题库始终直接浏览')}catch(e){setMessage(String(e))}}
  return <>
    <CatalogPackages locked={locked} onReload={reload}/>
    <QuestionIndexPackages locked={locked} onReload={reload}/>
    <section className="panel"><h2>学习助手设置</h2><AgentPrompt preferences={data.preferences} locked={locked} onReload={reload} onSaving={()=>{}}/>
      <p>网页使用一个固定学习会话。它会出现在 Codex 的会话列表中；网页连接期间，请在网页完成学习任务。当前已验证 CLI 的模型切换交接，Desktop 接管与释放尚未验证。</p>
      {agent.state?.connected&&<button disabled={locked} onClick={async()=>{try{agent.accept(await postJson('/api/agent/release',{}))}catch(e){setMessage(String(e))}}}>释放会话，去 CLI 切换模型</button>}
      {agent.state?.external_control&&<div className="notice"><p>在项目文件夹打开终端，运行下方命令；使用 /model 选择，完成后 /quit 退出 CLI，再在网页点击“重新连接原会话”。网页会读回保存的配置，仅菜单选择未保存时仍可能显示原值。</p><code>codex resume {agent.state.session_id}</code></div>}
    </section>
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
    <section className="panel"><h2>本地备份与修订</h2><p>备份包含个人原卷、照片、画像和记忆，请自行保管。恢复使用独立目录，不覆盖当前资料。</p><button disabled={locked} onClick={async()=>{try{const result=await postJson<{path:string}>('/api/maintenance/backup',{});setMessage('备份已保存：'+result.path)}catch(e){setMessage(String(e))}}}>创建本地备份</button><button onClick={async()=>setHistory(await (await fetch('/api/versions')).json())}>查看修订历史</button>{history&&<><h3>作答与检验修订</h3>{history.versions.map(v=><details key={v.id}><summary>{v.created_at} · {v.kind} · {v.reason}</summary><p>历史记录已保存在本机。</p></details>)}<h3>诊断报告版本</h3>{history.reports.map(r=><p key={r.id}>{r.created_at} · {r.paper_id} </p>)}</>}</section>
  </>
}
