import type {ReactNode} from 'react'
import type {Probe,PracticeGoal} from './LearningWorkspace'
import type {Paper} from './types'
import {MathText} from './MathText'

export function practiceStatus(probe:Probe){
  const last=probe.attempts.at(-1)
  if(!last)return '未作答'
  if(!last.assessment)return '待批改'
  return last.assessment.correct===null?(last.assessment.needs_material?.length?'待补充材料':'待核对'):'已反馈'
}

function linked(probe:Probe,goal:PracticeGoal){
  if(probe.linked_goal_ids)return probe.linked_goal_ids.includes(goal.id)
  return probe.source_result_id===goal.result_id&&!!probe.goal_ids?.includes(goal.goal.id||'')
}

export function PracticeWorkspace({goals,probes,allProbes,papers,selectedGoalId,selectedProbeId,blocked,message,limitations,onSelectGoal,onOriginal,onRelated,renderProbe}:{
  goals:PracticeGoal[];probes:Probe[];allProbes:Probe[];papers:Paper[];selectedGoalId:string;selectedProbeId:string;blocked:boolean;message:string;limitations:string[];
  onSelectGoal:(goal:string,probe?:string)=>void;onOriginal:(number:number)=>void;onRelated:(probe:Probe)=>void;renderProbe:(probe:Probe)=>ReactNode
}){
  const current=probes.filter(p=>p.is_current!==false)
  const byId=new Map(allProbes.map(p=>[p.id,p]))
  const groups=goals.map(g=>({item:g,local:current.filter(p=>linked(p,g)),related:(g.related_probe_ids||[]).map(id=>byId.get(id)).filter((p):p is Probe=>!!p)}))
  const relatedCount=new Set(groups.flatMap(g=>g.related.map(p=>p.id))).size
  const known=new Set(groups.flatMap(g=>g.local.map(p=>p.id)))
  const ungrouped=current.filter(p=>!known.has(p.id))
  const selected=groups.find(g=>g.item.id===selectedGoalId)||(selectedProbeId?groups.find(g=>g.local.some(p=>p.id===selectedProbeId)):undefined)
  const legacy=selectedGoalId==='ungrouped'||(!selected&&ungrouped.some(p=>p.id===selectedProbeId))
  const pendingHistory=probes.filter(p=>p.review_reason)
  const history=probes.filter(p=>!p.review_reason&&p.attempts.length>0&&(blocked||p.is_current===false))
  const statusCounts=(items:Probe[])=>{
    const unique=[...new Map(items.map(p=>[p.id,p])).values()]
    return ['未作答','待批改','待补充材料','待核对','已反馈'].map(s=>{const count=unique.filter(p=>practiceStatus(p)===s).length;return count?`${count} 道${s}`:''}).filter(Boolean).join('，')
  }
  return <section className="practice-workspace" aria-label="按考点复习">
    <section className="panel practice-heading"><h2>本卷考点与训练目标</h2><p>{message}</p>
      {!blocked&&<small>{goals.length} 个目标，{current.length} 道本卷练习{relatedCount?`，${relatedCount} 道历史引用`:''}。共享题沿用同一份作答；已反馈不表示整个考点已掌握。</small>}
    </section>
    {!blocked&&<>
      {!selected&&!legacy?<>
        <div className="practice-goal-list">{groups.map(({item,local,related})=><button className="practice-goal-row" key={item.id} onClick={()=>onSelectGoal(item.id)}>
          <span><strong><MathText text={item.goal.label}/></strong><small>原卷第 {item.goal.question_numbers.join('、')} 题{item.goal.stage!=='unknown'?` · ${({entry:'切入',modeling:'建模',formula:'公式应用',calculation:'计算',finalization:'最终处理'} as Record<string,string>)[item.goal.stage]||''}`:''}</small></span>
          <span className="practice-row-state">{local.length||related.length?<><b>{local.length} 道本卷{related.length?` · ${related.length} 道历史引用`:''}</b><small>{statusCounts([...local,...related])}</small></>:<b>{item.goal.decision==='no_candidate'?'本轮未选到合适题':'暂缓安排'}</b>}<span>查看目标与练习</span></span>
        </button>)}</div>
        {!!ungrouped.length&&<button className="panel practice-goal-row" onClick={()=>onSelectGoal('ungrouped')}><strong>已保存练习</strong><span>{ungrouped.length} 道 · 尚未关联到当前目标</span></button>}
        {!groups.length&&!ungrouped.length&&<section className="panel"><p>尚无本轮练习安排。原卷核对通过后会自动筛选；没有合适题时保留目标和检索说明。</p></section>}
      </>:<>
        <button className="small-action practice-back" onClick={()=>onSelectGoal('')}>返回全部考点</button>
        {selected&&<section className="panel practice-goal-detail"><h2><MathText text={selected.item.goal.label}/></h2>
          <div className="image-actions">{selected.item.goal.question_numbers.map(n=><button key={n} className="small-action" onClick={()=>onOriginal(n)}>回看原卷第{n}题</button>)}</div>
          <h3>为什么练</h3><p><MathText text={selected.item.goal.evidence}/></p><p><MathText text={selected.item.goal.reason}/></p>
          <p className="muted">{statusCounts([...selected.local,...selected.related])||'本轮未安排题目。可继续其他目标，也可使用上方“追加题目”再次检索。'}</p>
        </section>}
        <div className="probe-list">{(legacy?ungrouped:selected?.local||[]).map(renderProbe)}</div>
        {selected?.related.map(p=>{const paper=papers.find(pp=>pp.id===p.paper_id);return <article className="panel practice-related" key={p.id}>
          <div><strong>沿用已有练习</strong><p>{paper?.title||'来源卷暂不可用'} · 数学{['?','一','二','三'][p.access.math_type]} · {p.access.year} · 第{p.access.number}题</p><small>{practiceStatus(p)}；沿用原照片、曝光与反馈，不重复布置。</small></div>
          <button disabled={!paper} onClick={()=>onRelated(p)}>{p.is_current===false||paper?.archived_at?'打开来源卷核对':p.attempts.at(-1)?.assessment?'查看原反馈':'继续这道练习'}</button>
        </article>})}
      </>}
      {!!limitations.length&&<details className="panel practice-notes"><summary>本轮选题说明与覆盖范围</summary>{limitations.map((s,i)=><p key={i}><MathText text={s}/></p>)}</details>}
    </>}
    {!!pendingHistory.length&&<details className="panel practice-history" open={pendingHistory.some(p=>p.id===selectedProbeId)||undefined}><summary>原题版本待核的历史练习 · {pendingHistory.length} 道</summary>{pendingHistory.map(renderProbe)}</details>}
    {!!history.length&&<details className="panel practice-history" open={history.some(p=>p.id===selectedProbeId)||undefined}><summary>历史作答与反馈 · {history.length} 道</summary>{history.map(renderProbe)}</details>}
  </section>
}
