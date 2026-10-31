import {useEffect,useMemo,useState} from 'react'
import type {Paper,Question,VisibleContext} from './types'
import type {Skill,Probe} from './LearningWorkspace'
import {MathText} from './MathText'
import {KnowledgeQuestions,readLinks,type LinkSummary} from './KnowledgeQuestions'
import {postJson} from './api'
import {KnowledgeTree,kindLabel} from './KnowledgeTree'
import {ancestorIds,knowledgeIndex,nodeKind,resolveKnowledgeId,scopeEvidence,treeView} from './knowledge-tree'

export type OpenEvidence=(paper:string,question:string,tab?:string,probe?:string)=>void
type Pending={source_id:string;paper_id:string;kind:string}
type Props={catalogOnly?:boolean;skills:Skill[];pendingSources?:Pending[];papers:Paper[];questions:Question[];probes:Probe[];paperId?:string;selectedId?:string;onSelect?:(id:string)=>void;studyType:number;onReload:()=>Promise<void>;onOpen:OpenEvidence;onContextChange?:(c:VisibleContext)=>void;locked?:boolean;questionView?:''|'completed'|'bank';questionOffset?:number;onQuestionView?:(view:'completed'|'bank')=>void;onQuestionOffset?:(offset:number)=>void;onOpenBank?:(id:string)=>void}
const names=['','一','二','三']

export function EvidenceProfile({catalogOnly=false,skills,pendingSources=[],papers,questions,probes,paperId,selectedId,onSelect,studyType,onReload,onOpen,onContextChange,locked,questionView,questionOffset,onQuestionView,onQuestionOffset,onOpenBank}:Props){
  const [localSelected,setLocalSelected]=useState(''),[query,setQuery]=useState('')
  const [summary,setSummary]=useState<LinkSummary>(),[summaryError,setSummaryError]=useState(''),[localView,setLocalView]=useState<''|'completed'|'bank'>(''),[localOffset,setLocalOffset]=useState(0),[indexGeneration,setIndexGeneration]=useState(0)
  const [organizing,setOrganizing]=useState(false),[message,setMessage]=useState('')
  const activePapers=useMemo(()=>papers.filter(p=>!p.archived_at&&(!paperId||p.id===paperId)),[papers,paperId])
  const ids=useMemo(()=>new Set(activePapers.map(p=>p.id)),[activePapers])
  const visibleSkills=useMemo(()=>skills.map(skill=>{
    const events=(skill.events||[]).filter(e=>ids.has(e.paper_id))
    const tasks=probes.filter(p=>ids.has(p.paper_id)&&(skill.probe_ids||[]).includes(p.id))
    const original=questions.filter(q=>ids.has(q.paper_id)&&(skill.question_ids||[]).includes(q.id))
    return {...skill,events,tasks,original,hasRecords:events.length>0||tasks.length>0||original.length>0}
  }),[skills,probes,questions,ids])
  const index=useMemo(()=>knowledgeIndex(visibleSkills),[visibleSkills])
  const selected=resolveKnowledgeId(index,selectedId??localSelected)
  const current=index.items.get(selected),group=!!current&&nodeKind(current)!=='atom'
  const view=useMemo(()=>treeView(index,false,query),[index,query])
  const scope=useMemo(()=>current?scopeEvidence(index,selected):null,[index,current,selected])
  const events=group?scope?.events||[]:current?.events||[]
  const pending=pendingSources.filter(p=>ids.has(p.paper_id))
  const refreshKey=JSON.stringify([skills.length,pendingSources.length,questions.map(q=>[q.id,q.correctness]),probes.map(p=>[p.id,p.attempts.map(a=>[a.id,a.assessment?.correct])])])
  useEffect(()=>{
    const abort=new AbortController();setSummaryError('')
    readLinks<LinkSummary>('/api/knowledge/links/summary'+(paperId?'?paper_id='+encodeURIComponent(paperId):''),abort.signal).then(value=>{if(!abort.signal.aborted)setSummary(value)}).catch(e=>{if(!abort.signal.aborted)setSummaryError(String(e))})
    return()=>abort.abort()
  },[paperId,refreshKey,indexGeneration])
  const activeView=questionView||localView||summary?.default_view||'bank',offset=questionOffset??localOffset
  const setOffset=(n:number)=>{setLocalOffset(n);onQuestionOffset?.(n)}
  const setQuestionView=(value:'completed'|'bank')=>{setLocalView(value);setLocalOffset(0);onQuestionView?.(value)}
  useEffect(()=>{if(current&&!view.visible.has(selected))setQuery('')},[selected])
  const choose=(id:string)=>{
    const item=index.items.get(id);if(!item)return
    setLocalSelected(id);setLocalOffset(0);onSelect?.(id)
    onContextChange?.({view:paperId?'试卷工作区':catalogOnly?'考点树':'个人画像',label:item.label,section:'考点定义与题目关联',paper_id:paperId})
  }
  const organize=async()=>{
    setOrganizing(true);setMessage('')
    try{
      const result=await postJson('/api/knowledge/organize'+(paperId?'?paper_id='+encodeURIComponent(paperId):''),{}) as {jobs:unknown[]}
      setMessage(result.jobs.length?'已排入考点整理，连接 Codex 后依次处理；原始分析和作答保留。':'当前证据已整理。')
      window.dispatchEvent(new Event('mathlens:agent-refresh'));await onReload()
    }catch(error){setMessage(String(error))}finally{setOrganizing(false)}
  }
  const breadcrumb=current?[...ancestorIds(index,selected),selected]:[]
  return <div className="profile-workspace">
    {!paperId&&!catalogOnly&&<ScoreTrend papers={activePapers} studyType={studyType} onOpen={onOpen}/>}
    <section className="panel knowledge-panel">
      <div className="section-toolbar"><div><h2>{catalogOnly?'考点树':'考点目录与学习证据'}</h2><p className="knowledge-intro">同一份目录，查看已完成题目或全部题库。没有个人记录不代表薄弱。</p></div><div className="segmented" role="group" aria-label="关联题目视图">{([['completed','已完成题目'],['bank','全部题库']] as const).map(([value,label])=><button key={value} aria-pressed={activeView===value} className={activeView===value?'active':''} onClick={()=>setQuestionView(value)}>{label}</button>)}</div></div>
      {summaryError&&<p className="notice" role="alert">{summaryError}</p>}
      {!!pending.length&&<div className="notice"><strong>{pending.length} 份已保存证据待整理</strong><p>关联到统一考点；保留原始分析和判分。</p><button disabled={locked||organizing} onClick={organize}>{organizing?'正在排入…':'整理已有证据'}</button></div>}
      {message&&<p className="muted" role="status">{message}</p>}
      <div className="knowledge-browser-toolbar"><label className="knowledge-search"><span>查找考点</span><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="名称、别名或考点编号" aria-label="搜索考点"/>{query&&<button onClick={()=>setQuery('')} aria-label="清除考点搜索">×</button>}</label><span className="knowledge-catalog-count">{visibleSkills.filter(s=>nodeKind(s)==='atom').length} 个原子考点{query.trim()?`，${view.matches.size} 项匹配`:''}</span></div>
      {!skills.length?<div className="empty-state">当前没有可用考点目录。可在设置中导入通用目录；已保存试卷和作答会保留。</div>:<div className="knowledge-browser">
        <aside className="knowledge-sidebar"><KnowledgeTree index={index} visible={view.visible} selected={selected} query={query} onSelect={choose} counts={summary?.nodes} questionView={activeView}/>{!view.visible.size&&<div className="knowledge-search-empty"><p>当前范围未找到匹配考点。</p></div>}</aside>
        <div className="knowledge-reading" aria-live="polite">
          {!current?<div className="knowledge-start"><h3>{selected?'当前目录中未找到这个考点':'选择一个考点'}</h3><p>{selected?'可搜索名称或别名重新定位，已保存材料不会删除。':'展开左侧章节，查看定义、适用条件和已有学习记录。'}</p><p className="muted">目录统一维护；解题方法、计算步骤和可能错因保留在具体题目中。</p></div>:<>
            <nav aria-label="当前考点路径" className="knowledge-breadcrumb">{breadcrumb.map((id,i)=><span key={id}>{i>0&&<span aria-hidden="true"> / </span>}<button onClick={()=>choose(id)} aria-current={id===selected?'page':undefined}>{index.items.get(id)?.label}</button></span>)}</nav>
            {!view.visible.has(selected)&&<p className="muted">当前考点不在筛选结果中。<button className="small-action" onClick={()=>{setQuery('')}}>显示当前考点</button></p>}
            <div className="knowledge-detail-heading"><span className="knowledge-kind">{kindLabel(nodeKind(current))}</span><h2><MathText text={current.label}/></h2>{group?<p>本范围有 {scope?.atoms} 个原子考点，{scope?.recordedAtoms} 个已有学习记录。下方材料合并子考点并去重，不据此判断整章掌握。</p>:<p><span className={`status ${current.state==='需要关注'?'pending':['未覆盖','证据不足'].includes(current.state)?'neutral':'done'}`}>{current.state==='未覆盖'?'暂无学习证据':current.state}</span> {current.state_reason}</p>}</div>
            <KnowledgeDefinition item={current}/>
            {paperId&&<p className="muted">状态综合历史证据；已完成题目按本卷显示，全部题库不限来源试卷。</p>}
            <KnowledgeQuestions topicId={selected} questionView={activeView} offset={offset} paperId={paperId} summary={summary} onRefreshSummary={()=>setIndexGeneration(n=>n+1)} onView={setQuestionView} onOffset={setOffset} onTopic={choose} onOpen={onOpen} onBank={onOpenBank||((id)=>{location.href='/?view=bank&bank_id='+encodeURIComponent(id)})}/>
            {!!events.length&&<details className="knowledge-evidence"><summary>已记录的表现 · {events.length} 条{group?'（含子考点）':''}</summary>{events.map((event,i)=><p key={event.id||i}><span className="muted">{event.created_at.slice(0,10)}</span> · {({exam_error:'原卷相关错误',exam_success:'原卷相关成功',probe_failure:'独立检验有误',probe_success:'独立检验成功',assisted_failure:'参考解析后仍有误',assisted_success:'参考解析后完成',incomplete:'未完成，原因未知',hypothesis:'原因待观察'} as Record<string,string>)[event.kind]||'待核实证据'}</p>)}</details>}
          </>}
        </div>
      </div>}
      <p className="muted knowledge-scope-note">目录及其来源用于组织知识，不代表当年官方考纲范围的完整认证。</p>
    </section>
  </div>
}

function KnowledgeDefinition({item}:{item:Skill}){
  const origin=item.origin
  return <div className="knowledge-definition">
    {origin?.definition?<div className="knowledge-definition-text"><MathText text={origin.definition} implicit/></div>:<p className="muted">这个目录分组尚未单列定义，可展开查看子考点。</p>}
    {!!origin?.conditions?.length&&<section><h3>适用条件</h3><ul>{origin.conditions.map((text,i)=><li key={i}><MathText text={text} implicit/></li>)}</ul></section>}
    {!!origin?.boundaries?.length&&<section><h3>边界与辨析</h3><ul>{origin.boundaries.map((text,i)=><li key={i}><MathText text={text} implicit/></li>)}</ul></section>}
    {!!item.aliases?.length&&<p className="knowledge-aliases"><b>也称：</b>{item.aliases.join('、')}</p>}
    <details className="knowledge-provenance"><summary>来源与版本</summary><p>考点编号：<code>{item.skill_id}</code></p>{origin?.source_refs?.length?<ul>{origin.source_refs.map(ref=><li key={ref.source_version_id+ref.source_id}><code>{ref.source_id}</code><small title={ref.source_version_id}>来源版本 {ref.source_version_id.slice(0,19)}…</small></li>)}</ul>:<p className="muted">暂无单独登记的来源记录。</p>}{origin?.review_note&&<p><MathText text={origin.review_note}/></p>}{origin?.catalog_revision&&<small title={origin.catalog_revision}>目录版本 {origin.catalog_revision.slice(0,22)}…</small>}</details>
  </div>
}

function ScoreTrend({papers,studyType,onOpen}:{papers:Paper[];studyType:number;onOpen:OpenEvidence}){
  const [category,setCategory]=useState(studyType)
  const scored=papers.filter(p=>p.math_type===category&&p.score_confirmed_at&&Number.isFinite(p.score)&&p.total_score&&p.total_score>0).sort((a,b)=>(a.exam_date||a.created_at||'').localeCompare(b.exam_date||b.created_at||''))
  const latest=scored.at(-1),comparable=scored.filter(p=>p.total_score===latest?.total_score),previous=comparable.at(-2)
  const points=comparable.map((p,i)=>({x:comparable.length===1?300:24+i*552/(comparable.length-1),y:125-(p.score||0)/(p.total_score||150)*105,p}))
  return <section className="panel score-trend"><div className="section-toolbar"><div><div className="eyebrow">核定成绩</div><h2>试卷分数变化</h2></div><div className="segmented" role="group" aria-label="成绩数学类别">{[1,2,3].map(n=><button key={n} aria-pressed={category===n} className={category===n?'active':''} onClick={()=>setCategory(n)}>数学{names[n]}</button>)}</div></div>
    {latest?<><div className="trend-summary"><strong>{latest.score}<small> / {latest.total_score}</small></strong><span>{previous?`较上一份同类别同满分试卷 ${(latest.score||0)-(previous.score||0)>=0?'+':''}${Number(((latest.score||0)-(previous.score||0)).toFixed(2))} 分`:'只有一份核定成绩，继续积累试卷'}</span></div><svg viewBox="0 0 600 160" className="score-chart" role="img" aria-label="按作答日期排列的核定成绩变化"><line x1="24" y1="125" x2="576" y2="125" stroke="currentColor" opacity=".15"/><polyline points={points.map(p=>`${p.x},${p.y}`).join(' ')} fill="none" stroke="currentColor" strokeWidth="3"/>{points.map(({x,y,p})=><g key={p.id}><circle cx={x} cy={y} r="5" fill="currentColor"/><text x={x} y={y-12} textAnchor="middle">{p.score}</text><text x={x} y="149" textAnchor="middle">{(p.exam_date||'日期待填').slice(5)}</text></g>)}</svg><p className="muted">比较同类别、同满分的核定成绩。试卷难度与考试条件可能不同，分数变化需要结合逐题证据解释。</p><div className="score-history">{scored.map(p=><button className="evidence-row" key={p.id} onClick={()=>onOpen(p.id,'','diagnosis')}><span>{p.exam_date||'日期未填'} · {p.title}</span><strong>{p.score} / {p.total_score}</strong></button>)}</div></>:<div className="empty-state">暂无数学{names[category]}的核定成绩。请在试卷卡片中核定总分；未知分数不会记作 0 分。</div>}
  </section>
}
