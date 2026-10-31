import { useEffect, useState } from 'react'
import { postJson } from './api'
import type { Paper, Question, VisibleContext } from './types'

import { MathText } from './MathText'
import { useAnswerImages, AnswerImagePicker, SubmittedImages } from './AnswerImages'
import {useDraft} from './drafts'
import {BankGate} from './BankGate'
import {EvidenceProfile} from './EvidenceProfile'
import {QuestionReview} from './QuestionReview'
import {PracticeWorkspace,practiceStatus} from './PracticeWorkspace'
import {PracticeFeedback,type PracticeAssessment} from './PracticeFeedback'
import type {QuestionReviewRecord} from './QuestionReview'
export {EvidenceProfile} from './EvidenceProfile'
import type {BankQuestion} from './types'
export { MathText } from './MathText'

export type Diagnosis = {
  number: number; stem: string; correctness: string; observation: string; reference_answer: string;
  reference_reasoning: string; grading_note?: string; hypotheses: { id: string; label: string; evidence: string; alternative: string; correction: string; minimal_check?:string }[];
  regions: { page: number; bbox: number[]; role: string }[]; fingerprint: Record<string, unknown>
  correct_parts?:string[];first_error?:{stage:string;step:string;evidence:string}|null
  solution_guide?:{entry_point:string;strategy:string;key_steps:string[];pitfalls:string[]}|null;cause_summary?:string
  knowledge?:string[]
  answer_evidence?:{student_work:string;student_state:'visible'|'not_attempted'|'unreadable';marking:'none'|'correct'|'wrong'|'unclear';marking_note:string}
}
export type Probe = {
  review_reason?:string
  id: string; paper_id: string; question_id: string; question_ids?:string[]; bank_id: string; skill_id: string; skill_label: string;
  prompt: string; targets: string; discriminates: string; expected?: string; solution_note?: string;
  status: string; priority: number; question_image?: string; analysis_image?: string; question_text?:string; analysis_text?:string; bank_exposed: boolean;is_current?:boolean;
  access:BankQuestion;
  linked_goal_ids?:string[];goal_ids?:string[];source_result_id?:string;
  attempts: { id: string; response: string; image_ids?:string[];image_roles?:Record<string,string>; answer_exposed: number; assessment?: PracticeAssessment }[]
}
export type Skill = { skill_id: string; label: string; failures: number; successes: number; pending: number; papers: number; state: string; state_reason?:string;assisted_successes?:number;independent_probe_successes: number;probe_ids?:string[];question_ids?:string[];parent_id?:string|null;scope_level?:string;aliases?:string[];previous_ids?:string[];origin?:{catalog_revision?:string;node_kind?:string;definition?:string;conditions?:string[];boundaries?:string[];math_types?:number[];source_refs?:{source_id:string;source_version_id:string}[];review_note?:string};scopes?:{source_id:string;paper_id:string;reason:string}[];events?:{id?:string;paper_id:string;question_id?:string;probe_id?:string;kind:string;created_at:string}[] }
export type PracticeGoal={id:string;paper_id:string;result_id?:string;related_probe_ids?:string[];goal:{id?:string;label:string;question_numbers:number[];stage:string;evidence:string;reason:string;decision:string;priority?:number}}
export type Loop = { reports: { id: string; paper_id: string; summary: string; needs_completion?:boolean; needs_verification?:boolean; review?:{status:string;issues:string[]}; limitations: string[]; author: string; method: string; score_status: string; priorities: { label: string; evidence: string; action: string }[] }[];
  diagnoses: Record<string, Diagnosis>; probes: Probe[]; skills: Skill[];knowledge?:Skill[];knowledge_index?:{pending_sources:{source_id:string;paper_id:string;kind:string}[];reference:{title:string;status:string}};
  question_reviews?:QuestionReviewRecord[];
  tasks?:{id:string;paper_id:string;kind:string;status:string;error?:string}[];
  practice_states?:{paper_id:string;report_id:string;result_id:string|null;is_current:boolean;last_added_count?:number;last_retained_count?:number;limitations?:string[]}[];
  goals?:PracticeGoal[];
  summaries?:{id:string;paper_id:string;created_at:string;summary:{overview:string;key_findings:{text:string}[];improvements:{text:string}[];unknowns:string[];unfinished:string[];next_focus:string[]}}[] }

export function LearningWorkspace({ loop, questions, papers, onReload, paperId, selectedId, selectedProbeId='', selectedGoalId='', selectedKnowledgeId, onSelectKnowledge, onOpenRelated, activeTab, onNavigate, locked, onContextChange }: { loop: Loop; questions: Question[]; papers: Paper[]; onReload: () => Promise<void>;paperId:string;selectedId:string;selectedProbeId?:string;selectedGoalId?:string;selectedKnowledgeId?:string;onSelectKnowledge?:(id:string)=>void;onOpenRelated:(p:Probe)=>void;activeTab:string;onNavigate:(q:string,t:string,p?:string,g?:string)=>void;locked:boolean; onContextChange: (context: VisibleContext) => void }) {
  const tab=['diagnosis','probes','profile','summary'].includes(activeTab)?activeTab:'diagnosis'
  const setTab=(next:string)=>onNavigate(selectedId,next)
  const [storedProbe, setActiveProbe] = useDraft('paper:'+paperId+':probe','')
  const activeProbe=selectedProbeId||storedProbe
  useEffect(()=>{if(selectedProbeId)document.getElementById('probe-'+selectedProbeId)?.scrollIntoView({block:'center'})},[selectedProbeId,tab])
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [analyzing,setAnalyzing]=useState(false),[analyzeMessage,setAnalyzeMessage]=useState('')
  const analyze=async()=>{if(report&&!confirm('重新分析并核对本卷？旧报告和真实作答保留，核对通过后将由独立阶段准备练习。'))return;setAnalyzing(true);setAnalyzeMessage('');try{await postJson(`/api/papers/${paperId}/analyze`,{confirmed:!!report});setAnalyzeMessage('分析已排入；结果先可阅读，核对通过后将自动准备练习。未连接时材料保留，连接后继续。');window.dispatchEvent(new Event('mathlens:agent-refresh'));await onReload()}catch(e){setAnalyzeMessage(String(e))}finally{setAnalyzing(false)}}
  const selectExercises=async()=>{setAnalyzing(true);setAnalyzeMessage('');try{await postJson('/api/agent/task',{kind:'prepare_practice',paper_id:paperId,request_id:crypto.randomUUID()});setAnalyzeMessage('筛选任务已提交；完成后查看新增与保留的练习。');window.dispatchEvent(new Event('mathlens:agent-refresh'));await onReload()}catch(e){setAnalyzeMessage(String(e))}finally{setAnalyzing(false)}}
  const summarize=async()=>{if(summary&&!confirm('更新本卷总结？将按已保存分析和作答重新聚合，旧总结与原始证据保留。'))return;setAnalyzing(true);setAnalyzeMessage('');try{await postJson(`/api/papers/${paperId}/resummarize`,{confirmed:true});window.dispatchEvent(new Event('mathlens:agent-refresh'));await onReload()}catch(e){setAnalyzeMessage(String(e))}finally{setAnalyzing(false)}}
  const report = loop.reports.find(r => r.paper_id === paperId)
  const paper = papers.find(p => p.id === paperId)
  const list = questions.filter(q => q.paper_id === paperId).sort((a,b) => Number(a.number)-Number(b.number))
  const selected = list.find(q => q.id === selectedId) || list[0]
  useEffect(() => { setExpanded((old): Record<string, boolean> => old['本轮识别边界与来源'] ? {'本轮识别边界与来源': true} : {}) }, [selected?.id, tab])
  const diagnosis = selected && loop.diagnoses[selected.id]
  const probes = loop.probes.filter(p => p.paper_id === paperId)
  const preparing=!!loop.tasks?.some(t=>t.paper_id===paperId&&t.kind==='prepare_practice'&&['queued','running','repairing','result_saved'].includes(t.status))
  const practiceState=loop.practice_states?.find(p=>p.paper_id===paperId)
  const stalePlan=practiceState?.is_current===false
  const exercisesBlocked=!!report?.needs_verification||stalePlan||preparing
  const practiceLabel=report?.needs_verification?'待核对':preparing?'筛选中':stalePlan?'待筛选':null
  const selectionLabel=preparing?'正在筛选…':practiceState?.is_current?'追加题目':'筛选题目'
  const goals=(loop.goals||[]).filter(g=>g.paper_id===paperId)
  const summary=loop.summaries?.find(s=>s.paper_id===paperId)
  const probe = tab === 'probes' ? probes.find(p => p.id === activeProbe) : undefined
  const currentQuestion = tab === 'diagnosis' ? selected : probe ? questions.find(q => q.id === probe.question_id) : undefined
  const section = ({diagnosis:'原卷与诊断', probes:'针对性检验', profile:'本卷证据'} as Record<string,string>)[tab]
  const contextKey = JSON.stringify({ view: '试卷工作区', label: probe ? probe.skill_label||`${probe.access.year} 第${probe.access.number}题候选` : currentQuestion ? `第 ${currentQuestion.number} 题 · ${currentQuestion.stem}` : paper?.title || '试卷工作区',
    section, paper_id: paper?.id, question_id: currentQuestion?.id, probe_id: probe?.id, bank_id: probe?.bank_id,
    expanded: Object.keys(expanded).filter(k => expanded[k] && (k.startsWith(`${currentQuestion?.id}:`) || k === '本轮识别边界与来源')).map(k => k.split(':').at(-1)!) })
  useEffect(() => { onContextChange(JSON.parse(contextKey)) }, [contextKey, onContextChange])
  const toggle = (key: string, open: boolean) => setExpanded(old => old[key] === open ? old : {...old, [key]: open})
  if (!report) return <section className="panel"><h2>本卷等待分析</h2><p>{list.length} 道题已初步定位。连接学习助手后分阶段分析与准备练习；等待中的材料和任务会保留。</p><a href={`/api/papers/${paperId}/file`} target="_blank" rel="noreferrer">打开原卷</a><button disabled={locked||analyzing} onClick={analyze}>{analyzing?'正在准备…':'分析本卷'}</button>{analyzing&&<div className="activity-track" role="progressbar" aria-label="正在核对切分并准备分析"><span/></div>}{analyzeMessage&&<p role="status" className="notice">{analyzeMessage}</p>}<div className="number-strip">{list.map(q=><button key={q.id} onClick={()=>onNavigate(q.id,'diagnosis')}>第{q.number}题</button>)}</div>{selected&&<><h3><MathText text={selected.stem}/></h3>{selected.page_start&&<img className="evidence-image" src={`/api/questions/${selected.id}/evidence`} alt="初步切分区域"/>}</>}</section>
  const relatedIds=new Set(goals.flatMap(g=>g.related_probe_ids||[]))
  const pending = loop.probes.filter(p => p.is_current!==false&&(p.paper_id===paperId||relatedIds.has(p.id))&&practiceStatus(p)!=='已反馈').length
  return <div className="learning-workspace">
    <section className="panel loop-intro"><div className="eyebrow">本卷复习</div><h2>{paper?.title}</h2><p><MathText text={report.summary}/></p>
      {report.needs_completion&&<div className="notice"><p>已有分析尚不完整，下方保留原有观察；可按新流程重新核对本卷。</p></div>}
      {report.needs_verification&&<div className="notice"><strong>初步分析仍需核对，练习暂缓</strong><p>选择下方待核题，点击“重新核对本题”。助手会重读原图；说明和补图均可选。整卷核对通过后自动筛选练习。</p>{report.review?.issues.map((s,i)=><p key={i}><MathText text={s}/></p>)}<div className="image-actions">{list.filter(q=>q.correctness==='unknown'||loop.diagnoses[q.id]?.answer_evidence?.student_state==='unreadable'&&!['wrong','correct'].includes(loop.diagnoses[q.id]?.answer_evidence?.marking||'none')).map(q=><button key={q.id} onClick={()=>onNavigate(q.id,'diagnosis')}>核对第{q.number}题</button>)}</div></div>}
      <div className="section-toolbar"><button className="small-action" disabled={locked||analyzing} onClick={analyze}>重新分析本卷…</button><button className="primary" disabled={locked||analyzing||preparing||!!report.needs_verification||!!report.needs_completion} onClick={selectExercises}>{selectionLabel}</button></div><p className="muted">根据本卷考点和可能错因筛选练习；允许继续追加，已有题目和作答保留。</p>
      <div className="loop-metrics"><span><b>{list.length}</b>题已定位</span><span><b>{report.needs_completion?'待补全':list.filter(q=>q.correctness==='wrong'||q.correctness==='partial'||loop.diagnoses[q.id]?.answer_evidence?.student_state==='not_attempted').length}</b>{report.needs_completion?'题目判定':'题需补强（含未完成）'}</span><span><b>{practiceLabel||pending}</b>{practiceLabel?'练习准备':'个练习待完成'}</span><span><b>{paper?.score_confirmed_at?paper.score:'待核定'}</b>{paper?.score_confirmed_at?'用户核定总分':'总分'}</span></div>
      <small><MathText text={paper?.score_confirmed_at?'总分已由你核定；逐题评分仍以诊断证据为准。':({unknown:'总分尚未核定',estimated:'逐题评分为估计，请以核定总分为准'} as Record<string,string>)[report.score_status]||report.score_status}/></small>
    </section>
    {analyzeMessage&&<p role="status" className="notice">{analyzeMessage}</p>}
    <div className="loop-tabs">{[['diagnosis','原卷解析'],['probes','补强练习'],['summary','本卷总结'],['profile','本卷证据']].map(([id,label])=><button key={id} className={tab===id?'filter active':'filter'} onClick={()=>setTab(id)}>{label}{id==='probes'&&` · ${practiceLabel||pending}`}</button>)}</div>
    {tab==='diagnosis' && <>
      <div className="priority-grid">{report.priorities.map(p=><article className="panel" key={p.label}><span className="eyebrow">本轮优先</span><h3><MathText text={p.label}/></h3><p><MathText text={p.evidence}/></p><strong><MathText text={p.action}/></strong></article>)}</div>
      <div className="number-strip">{list.map(q=><button key={q.id} title={q.notes} className={`number-chip ${q.id===selected?.id?'selected':''} ${q.correctness}`} onClick={()=>onNavigate(q.id,'diagnosis')}>{q.number}<small>{loop.diagnoses[q.id]?.answer_evidence?.student_state==='not_attempted'?'未作答':({correct:'正确',wrong:'有误',partial:'部分完成',unknown:'正误待核'} as Record<string,string>)[q.correctness]||'正误待核'}</small></button>)}</div>
      {selected && diagnosis && <div className="evidence-columns"><section className="panel"><div className="eyebrow">原卷证据 · 第{selected.number}题</div><h3><MathText text={diagnosis.stem}/></h3>
        {diagnosis.regions.map((r,index)=><figure key={index}><img className="evidence-image" src={`/api/questions/${selected.id}/evidence?region=${index}`} alt={`第${selected.number}题原卷第${r.page}页区域${index+1}`} /><figcaption>原卷第{r.page}页 · {r.role==='supplemental_work'?'同题补充作答区域':'题目及作答区域'}</figcaption></figure>)}
        <a href={`/api/papers/${selected.paper_id}/file#page=${selected.page_start}`} target="_blank" rel="noreferrer">打开完整原卷</a>
      </section><section className="panel"><div className="eyebrow">解法与作答分析</div>
        <section className="question-knowledge"><h3>本题考点与训练环节</h3>{diagnosis.knowledge?.length?<div className="knowledge-tags">{diagnosis.knowledge.map((point,i)=><span key={i}><MathText text={point}/></span>)}</div>:<p className="muted">本题暂未保存具体考点；下次分析时由助手补齐。</p>}{(['methods','operations'] as const).map(key=>{const values=diagnosis.fingerprint[key];return Array.isArray(values)&&values.length?<p key={key}><b>{key==='methods'?'解题方法':'必要操作'}：</b><MathText text={values.filter(v=>typeof v==='string').join('、')}/></p>:null})}<small>用于关联复习题目；题目涉及的考点不等于已确认的薄弱点。</small></section>
        <QuestionReview key={`${selected.id}:${report.id}`} questionId={selected.id} reportId={report.id} number={String(selected.number)} unresolved={diagnosis.correctness==='unknown'||diagnosis.answer_evidence?.student_state==='unreadable'&&!['wrong','correct'].includes(diagnosis.answer_evidence.marking)} locked={locked||analyzing} records={loop.question_reviews||[]} onReload={onReload}/>
        <p className="observation"><MathText text={diagnosis.observation}/></p>
        {diagnosis.answer_evidence&&<div className="probe-prompt"><p><b>原作答：</b><MathText text={diagnosis.answer_evidence.student_work||({'not_attempted':'未见作答','unreadable':'暂无法辨认'} as Record<string,string>)[diagnosis.answer_evidence.student_state]||'未转录'}/></p><p><b>事后批改：</b><MathText text={diagnosis.answer_evidence.marking_note||'未见明确批改'}/></p></div>}
        {!!diagnosis.correct_parts?.length&&<div><h3>已完成的正确部分</h3>{diagnosis.correct_parts.map((s,i)=><p key={i}><MathText text={s}/></p>)}</div>}
        {diagnosis.first_error&&<div className="notice"><strong>首个实质性错误</strong><p><MathText text={diagnosis.first_error.step}/></p><p><MathText text={diagnosis.first_error.evidence}/></p></div>}
        {diagnosis.correctness==='wrong'&&!diagnosis.first_error&&<p>{diagnosis.answer_evidence?.student_state==='not_attempted'?'本题未作答，将依据考点与必要操作安排补强；空白原因仍保留未知。':'已判错；具体出错环节尚未明确，不影响本题正误记录。'}</p>}
        {diagnosis.cause_summary&&<section className="hypothesis"><h3>可能原因与排查思路</h3><p><MathText text={diagnosis.cause_summary}/></p><small>结合本题考点用于后续选题；可能原因保留不确定性。</small></section>}
        {diagnosis.solution_guide&&<section className="solution-guide"><h3>切入点</h3><p><MathText text={diagnosis.solution_guide.entry_point}/></p><h3>整体思路</h3><p><MathText text={diagnosis.solution_guide.strategy}/></p><h3>关键步骤</h3><ol>{diagnosis.solution_guide.key_steps.map((step,i)=><li key={i}><MathText text={step}/></li>)}</ol><h3>注意事项</h3><ul>{diagnosis.solution_guide.pitfalls.map((tip,i)=><li key={i}><MathText text={tip}/></li>)}</ul></section>}
        {diagnosis.hypotheses.map(h=><article className="hypothesis" key={h.id}><span className="status pending">可能原因 · 供参考</span><h3><MathText text={h.label}/></h3><p><b>依据：</b><MathText text={h.evidence}/></p>{h.alternative&&<p><b>其他可能：</b><MathText text={h.alternative}/></p>}{h.correction&&<p><b>建议：</b><MathText text={h.correction}/></p>}</article>)}
        {!diagnosis.solution_guide&&<p className="muted">这是旧版分析。重新分析可补齐切入点、思路和注意事项。</p>}
        <details open key={`${selected.id}:reference`} onToggle={e=>toggle(`${selected.id}:参考结论与关键推导`,e.currentTarget.open)}><summary>解题思路与关键推导</summary><p><MathText text={diagnosis.reference_answer}/></p><p><MathText text={diagnosis.reference_reasoning}/></p></details>
        {diagnosis.grading_note&&<p className="muted"><MathText text={diagnosis.grading_note}/></p>}
        <details key={`${selected.id}:fingerprint`}><summary>题目结构</summary>{Object.entries({conditions:'条件',goal:'目标',methods:'方法',operations:'操作环节',objects:'对象',method:'方法',stages:'环节'}).map(([key,label])=>{const value=diagnosis.fingerprint[key];return typeof value==='string'||Array.isArray(value)?<p key={key}><b>{label}：</b><MathText text={typeof value==='string'?value:value.filter(v=>typeof v==='string').join('、')}/></p>:null})}</details>
        {probes.some(p=>p.question_id===selected.id||p.question_ids?.includes(selected.id))&&<button className="primary full" onClick={()=>setTab('probes')}>查看补强练习</button>}
      </section></div>}
    </>}
    {tab==='probes'&&<PracticeWorkspace goals={goals} probes={probes} allProbes={loop.probes} papers={papers} selectedGoalId={selectedGoalId} selectedProbeId={selectedProbeId} blocked={!!exercisesBlocked} message={report.needs_verification?'原卷仍有影响判定的疑点。核对通过后再筛选，历史作答保留。':preparing?'正在结合考点与可能错因筛选，已有材料保留；完成后可继续作答。':stalePlan?'原卷分析已更新，旧安排和作答保留；等待本轮筛选完成。':'先看本卷需要关注的考点，再进入对应练习。追加只补值得检验的缺口，已有题和作答保留。'} limitations={practiceState?.limitations||[]} onSelectGoal={(goal,pid='')=>onNavigate(selectedId,'probes',pid,goal)} onOriginal={number=>{const q=list.find(q=>Number(q.number)===number);if(q)onNavigate(q.id,'diagnosis')}} onRelated={onOpenRelated} renderProbe={p=><ProbeCard key={p.id} probe={p} active={p.id===activeProbe} locked={locked||!!exercisesBlocked||p.is_current===false} onReload={onReload} onSelect={()=>{setActiveProbe(p.id);onNavigate(p.question_id,'probes',p.id,selectedGoalId)}} onAnalysis={open=>toggle(`${currentQuestion?.id}:检验解析`,open)}/>}/>}
    {tab==='summary'&&<section className="panel"><div className="section-toolbar"><h2>本卷总结</h2><button className="primary" disabled={locked||analyzing} onClick={summarize}>{summary?'更新本卷总结':'总结本卷'}</button></div><p>汇总已经保存的分析和练习反馈，可以保留尚未完成的内容。</p>{summary?<><p><MathText text={summary.summary.overview}/></p>{[['主要发现',summary.summary.key_findings.map(f=>f.text)],['已有改善',summary.summary.improvements.map(f=>f.text)],['仍待明确',summary.summary.unknowns],['未完成内容',summary.summary.unfinished],['后续重点',summary.summary.next_focus]].map(([label,items])=><div key={String(label)}><h3>{String(label)}</h3>{(items as string[]).map((s,i)=><p key={i}><MathText text={s}/></p>)}</div>)}</>:<p>完成当前复习后，点击总结即可。</p>}</section>}
    {tab==='profile'&&<EvidenceProfile skills={loop.knowledge||[]} pendingSources={loop.knowledge_index?.pending_sources} papers={papers} questions={questions} probes={loop.probes} paperId={paperId} selectedId={selectedKnowledgeId} onSelect={onSelectKnowledge} studyType={paper?.math_type||1} onReload={onReload} onOpen={(_paper,question,next='diagnosis',pid)=>onNavigate(question,next,pid)} onContextChange={onContextChange} locked={locked}/>}
    <details className="panel limitations" onToggle={e=>toggle('本轮识别边界与来源',e.currentTarget.open)}><summary>本轮识别边界与来源</summary><p>{report.author} · {report.method}</p>{report.limitations.map((x,i)=><p key={i}><MathText text={x}/></p>)}</details>
  </div>
}

function ProbeCard({probe,onReload,onSelect,locked,onAnalysis,active}:{probe:Probe;onReload:()=>Promise<void>;onSelect:()=>void;locked:boolean;onAnalysis:(open:boolean)=>void;active?:boolean}){
  const photos=useAnswerImages('probe:'+probe.id),[response,setResponse]=useDraft('probe:'+probe.id+':text',''),[exposed,setExposed]=useDraft('probe:'+probe.id+':exposed',false),[requestId,setRequestId]=useDraft('probe:'+probe.id+':request',crypto.randomUUID())
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[supplement,setSupplement]=useState(false),[showAnalysis,setShowAnalysis]=useState(false)
  const last=probe.attempts.at(-1)
  const action=async(path:string,body:unknown)=>{setBusy(true);setError('');try{await postJson(path,body);await onReload();window.dispatchEvent(new Event('mathlens:agent-refresh'));return true}catch(e){setError(String(e));return false}finally{setBusy(false)}}
  const submit=async()=>{const body={response,image_ids:photos.images.map(i=>i.id),image_roles:Object.fromEntries(photos.images.map(i=>[i.id,i.role||'own_work'])),answer_exposed:exposed||probe.bank_exposed,request_id:requestId};if(await action(last?`/api/attempts/${last.id}/supplement`:`/api/probes/${probe.id}/submit`,body)){setResponse('');photos.clear();setSupplement(false);setRequestId(crypto.randomUUID())}}
  if(probe.review_reason){
    const provenance=[([1,2,3].includes(probe.access.math_type)?`数学${probe.access.math_type}`:null),probe.access.year||null,probe.access.number>0?`第${probe.access.number}题`:null].filter(Boolean).join(' · ')
    return <article id={'probe-'+probe.id} className="panel probe-card"><span className="eyebrow">历史练习 · {provenance||'来源待核'}</span><p>{probe.review_reason}</p>{last&&<div className="attempt-result"><b>原作答与反馈</b><MathText text={last.response||'照片材料'}/><SubmittedImages ids={last.image_ids} roles={last.image_roles}/>{last.assessment?<PracticeFeedback assessment={last.assessment}/>:<p>原作答保留，尚无可用批改。</p>}</div>}</article>
  }
  return <article id={'probe-'+probe.id} className={`panel probe-card ${active?'active-probe':''}`} tabIndex={0} onFocus={onSelect} onClick={onSelect}>
    {probe.is_current===false&&<p className="muted">历史练习与作答，保留供回顾。</p>}
    {!probe.access.can_view?<BankGate item={probe.access} reload={onReload}/>:<><span className="eyebrow">数学{probe.access.math_type} · {probe.access.year} · 第{probe.access.number}题</span><h3><MathText text={probe.skill_label}/></h3><p><b>本题练什么：</b><MathText text={probe.discriminates}/></p>{probe.question_image?<img className="evidence-image" src={probe.question_image} alt="练习原题"/>:<MathText text={probe.question_text||''}/>}<div className="probe-prompt"><MathText text={probe.prompt}/></div>
    {last&&<div className="attempt-result"><b>已保存的作答与材料</b><MathText text={last.response||'照片材料'}/><SubmittedImages ids={last.image_ids} roles={last.image_roles}/>{last.assessment?<PracticeFeedback assessment={last.assessment}/>:<p>作答已保存，将在连接就绪后批改；可在上方查看当前阶段。</p>}
      {!last.assessment&&<button className="small-action" disabled={locked||busy} onClick={()=>action(`/api/probes/${probe.id}/feedback`,{attempt_id:last.id})}>继续批改</button>}
      <button disabled={locked||busy} onClick={()=>setSupplement(!supplement)}>{supplement?'取消补充':'补充步骤或局部照片'}</button>
    </div>}
    {(!last||supplement)&&<fieldset disabled={locked||busy||photos.busy}><textarea aria-label={`${probe.skill_label}的作答`} placeholder={last?'补充缺少的步骤或重拍不清楚的区域。':'写思路或上传手写作答照片；不必转录整页。'} value={response} onChange={e=>setResponse(e.target.value)} onPaste={e=>{if(e.clipboardData.files.length){e.preventDefault();photos.addFiles(Array.from(e.clipboardData.files))}}}/><AnswerImagePicker draft={photos} disabled={locked||busy}/>{!last&&<label><input type="checkbox" checked={exposed||probe.bank_exposed} disabled={probe.bank_exposed} onChange={e=>setExposed(e.target.checked)}/>此前看过这道题的答案或解析</label>}<button className="primary" disabled={!response.trim()&&!photos.images.length} onClick={submit}>{last?'提交补充并批改':'提交作答并批改'}</button></fieldset>}
    <details onToggle={e=>{setShowAnalysis(e.currentTarget.open);onAnalysis(e.currentTarget.open)}}><summary>查看参考与解析</summary>{probe.access.analysis_allowed?<><MathText text={probe.expected||''}/><MathText text={probe.solution_note||''}/>{showAnalysis&&(probe.analysis_image?<img className="evidence-image" src={probe.analysis_image} alt="原题参考解析"/>:<MathText text={probe.analysis_text||''}/>)}</>:<><p>查看会记录解析曝光；原先已保存的独立作答仍保留，之后的补充另记。</p><button onClick={()=>action(`/api/bank/${probe.bank_id}/reveal`,{role:'analysis',confirmed:true})}>确认查看解析</button></>}</details></>}{error&&<p className="notice" role="alert">{error}</p>}</article>
}
