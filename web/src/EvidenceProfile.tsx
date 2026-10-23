import {useState} from 'react'
import type {Paper,Question,VisibleContext} from './types'
import type {Skill,Probe} from './LearningWorkspace'
import {MathText} from './MathText'
import {BankGate} from './BankGate'

export type OpenEvidence=(paper:string,question:string,tab?:string,probe?:string)=>void
type Props={skills:Skill[];papers:Paper[];questions:Question[];probes:Probe[];paperId?:string;studyType:number;onReload:()=>Promise<void>;onOpen:OpenEvidence;onContextChange?:(c:VisibleContext)=>void;locked?:boolean}
const names=['','一','二','三']

export function EvidenceProfile({skills,papers,questions,probes,paperId,studyType,onReload,onOpen,onContextChange,locked}:Props){
  const [selected,setSelected]=useState(''),[filter,setFilter]=useState('all')
  const activePapers=papers.filter(p=>!p.archived_at&&(!paperId||p.id===paperId)),ids=new Set(activePapers.map(p=>p.id))
  const visibleSkills=skills.map(skill=>{
    const events=(skill.events||[]).filter(e=>ids.has(e.paper_id))
    const tasks=probes.filter(p=>ids.has(p.paper_id)&&(skill.probe_ids||[]).includes(p.id))
    return {...skill,events,tasks}
  }).filter(s=>s.events.length||s.tasks.length)
  const current=visibleSkills.find(s=>s.skill_id===selected)
  const sourceIds=new Set([...(current?.events.map(e=>e.question_id).filter(Boolean)||[]),...(current?.tasks.map(p=>p.question_id)||[])])
  const original=questions.filter(q=>ids.has(q.paper_id)&&sourceIds.has(q.id))
  const done=(p:Probe)=>typeof p.attempts.at(-1)?.assessment?.correct==='boolean'
  const related=current?.tasks.filter(p=>filter==='all'||(filter==='done'?done(p):!done(p)))||[]
  const choose=(skill:Skill)=>{
    setSelected(skill.skill_id);setFilter('all')
    onContextChange?.({view:paperId?'试卷工作区':'个人画像',label:skill.label,section:'知识点证据',paper_id:paperId})
  }
  return <div className="profile-workspace">
    {!paperId&&<ScoreTrend papers={activePapers} studyType={studyType} onOpen={onOpen}/>}
    <section className="panel"><div className="eyebrow">{paperId?'本卷的学习证据':'跨卷学习证据'}</div><h2>{paperId?'本卷知识点':'知识点与解题环节'}</h2><p>点击查看对应原卷题、已完成检验和待处理任务。掌握情况由实际作答支持，浏览题目不计成功。</p>
      {!visibleSkills.length&&<div className="empty-state">还没有诊断证据。先上传试卷并让 Agent 写回逐题分析。</div>}
      <div className="skill-grid">{visibleSkills.map(s=>{
        const errors=s.events.filter(e=>['exam_error','probe_failure'].includes(e.kind)).length,success=s.events.filter(e=>['exam_success','probe_success'].includes(e.kind)).length
        return <button className={`skill-card skill-button ${selected===s.skill_id?'selected':''}`} key={s.skill_id} onClick={()=>choose(s)} aria-pressed={selected===s.skill_id}><h3><MathText text={s.label}/></h3><span className={`status ${errors?'pending':'done'}`}>{errors?'有失误证据，原因待复核':success?'有成功证据，待持续验证':'待验证'}</span><p>失误 {errors} · 成功 {success} · 待处理检验 {s.tasks.filter(p=>!done(p)).length}</p><small>{new Set([...s.events.map(e=>e.paper_id),...s.tasks.map(p=>p.paper_id)]).size} 份试卷 · 查看题目与过程 →</small></button>
      })}</div>
    </section>
    {current&&<section className="panel skill-detail"><div className="section-toolbar"><div><div className="eyebrow">证据详情</div><h2><MathText text={current.label}/></h2></div><button className="small-action" disabled={locked} onClick={()=>window.dispatchEvent(new CustomEvent('mathlens:discuss',{detail:`请审核知识点/环节「${current.label}」的现有原卷和检验作答，区分仍待检验的错误原因。若缺少合适检验，请阅读题库后添加少量有明确诊断目的的题目，不按标签自动添加。相关原卷题ID：${original.map(q=>q.id).join('、')||'请读取当前画像证据'}。`}))}>请 Agent 审核并补充检验</button></div>
      <h3>来自上传试卷 <span className="count-pill">{original.length}</span></h3>
      {original.map(q=><button className="evidence-row" key={q.id} onClick={()=>onOpen(q.paper_id,q.id,'diagnosis')}><span><strong>{papers.find(p=>p.id===q.paper_id)?.title} · 第{q.number}题</strong><small>{({wrong:'作答有误',partial:'部分完成',correct:'作答正确',unknown:'待核对'} as Record<string,string>)[q.correctness]||'待核对'}</small></span><span>查看原卷与诊断 →</span></button>)}
      {!original.length&&<p className="muted">尚无关联的原卷作答证据。</p>}
      <div className="section-toolbar"><h3>来自题库的检验</h3><div className="segmented" role="group" aria-label="知识点检验状态">{[['all','全部'],['done','已完成'],['pending','未完成']].map(([value,label])=><button key={value} aria-pressed={filter===value} className={filter===value?'active':''} onClick={()=>setFilter(value)}>{label}</button>)}</div></div>
      {!related.length&&<p className="muted">这个范围还没有检验题。由 Agent 阅读并审核后添加。</p>}
      {related.map(p=>{
        const last=p.attempts.at(-1),state=done(p)?last?.assessment?.correct?'已完成 · 正确':'已完成 · 有误':last?last.assessment?.correct===null?'未完成 · 需补充证据':'未完成 · 待评价':'未完成 · 待作答'
        return <article className="related-probe" key={p.id}><div className="paper-card-meta"><strong>数学{names[p.access.math_type]} · {p.access.year} · 第{p.access.number}题</strong><span className={`status ${done(p)?'done':'pending'}`}>{state}</span></div>
          {!p.access.can_view?<BankGate item={p.access} reload={onReload}/>:<><p><MathText text={p.discriminates||p.prompt}/></p><button className="evidence-row" onClick={()=>onOpen(p.paper_id,p.question_id,'probes',p.id)}>查看检验任务与作答 →</button></>}
        </article>
      })}
    </section>}
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
