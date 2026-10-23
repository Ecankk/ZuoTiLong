import { useEffect, useState } from 'react'
import { postJson } from './api'
import type { Paper, Question, VisibleContext } from './types'

import { MathText } from './MathText'
import { useAnswerImages, AnswerImagePicker, SubmittedImages } from './AnswerImages'
import {useDraft} from './drafts'
import {BankGate} from './BankGate'
import type {BankQuestion} from './types'
export { MathText } from './MathText'

export type Diagnosis = {
  number: number; stem: string; correctness: string; observation: string; reference_answer: string;
  reference_reasoning: string; grading_note?: string; hypotheses: { id: string; label: string; evidence: string; alternative: string; correction: string }[];
  regions: { page: number; bbox: number[]; role: string }[]; fingerprint: Record<string, unknown>
}
export type Probe = {
  id: string; paper_id: string; question_id: string; bank_id: string; skill_id: string; skill_label: string;
  prompt: string; targets: string; discriminates: string; expected?: string; solution_note?: string;
  status: string; priority: number; question_image?: string; analysis_image?: string; bank_exposed: boolean;
  access:BankQuestion;
  attempts: { id: string; response: string; image_ids?:string[]; answer_exposed: number; assessment?: { correct: boolean|null; feedback: string } }[]
}
export type Skill = { skill_id: string; label: string; failures: number; successes: number; pending: number; papers: number; state: string; independent_probe_successes: number }
export type Loop = { reports: { id: string; paper_id: string; summary: string; limitations: string[]; author: string; method: string; score_status: string; priorities: { label: string; evidence: string; action: string }[] }[];
  diagnoses: Record<string, Diagnosis>; probes: Probe[]; skills: Skill[] }

export function LearningWorkspace({ loop, questions, papers, onReload, paperId, selectedId, activeTab, onNavigate, locked, onContextChange }: { loop: Loop; questions: Question[]; papers: Paper[]; onReload: () => Promise<void>;paperId:string;selectedId:string;activeTab:string;onNavigate:(q:string,t:string)=>void;locked:boolean; onContextChange: (context: VisibleContext) => void }) {
  const tab=['diagnosis','probes','profile'].includes(activeTab)?activeTab:'diagnosis'
  const setTab=(next:string)=>onNavigate(selectedId,next)
  const [activeProbe, setActiveProbe] = useDraft('paper:'+paperId+':probe','')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const report = loop.reports.find(r => r.paper_id === paperId)
  const paper = papers.find(p => p.id === paperId)
  const list = questions.filter(q => q.paper_id === paperId).sort((a,b) => Number(a.number)-Number(b.number))
  const selected = list.find(q => q.id === selectedId) || list[0]
  useEffect(() => { setExpanded((old): Record<string, boolean> => old['本轮识别边界与来源'] ? {'本轮识别边界与来源': true} : {}) }, [selected?.id, tab])
  const diagnosis = selected && loop.diagnoses[selected.id]
  const probes = loop.probes.filter(p => p.paper_id === paperId)
  const probe = tab === 'probes' ? probes.find(p => p.id === activeProbe) : undefined
  const currentQuestion = tab === 'diagnosis' ? selected : probe ? questions.find(q => q.id === probe.question_id) : undefined
  const section = ({diagnosis:'原卷与诊断', probes:'针对性检验', profile:'初始画像'} as Record<string,string>)[tab]
  const contextKey = JSON.stringify({ view: '试卷工作区', label: probe ? probe.skill_label||`${probe.access.year} 第${probe.access.number}题候选` : currentQuestion ? `第 ${currentQuestion.number} 题 · ${currentQuestion.stem}` : paper?.title || '试卷工作区',
    section, paper_id: paper?.id, question_id: currentQuestion?.id, probe_id: probe?.id, bank_id: probe?.bank_id,
    expanded: Object.keys(expanded).filter(k => expanded[k] && (k.startsWith(`${currentQuestion?.id}:`) || k === '本轮识别边界与来源')).map(k => k.split(':').at(-1)!) })
  useEffect(() => { onContextChange(JSON.parse(contextKey)) }, [contextKey, onContextChange])
  const toggle = (key: string, open: boolean) => setExpanded(old => old[key] === open ? old : {...old, [key]: open})
  if (!report) return <section className="panel"><h2>本卷等待 Agent 诊断</h2><p>{list.length} 道题已初步定位。可在右侧要求 Agent 阅读本卷并写回诊断。</p><a href={`/api/papers/${paperId}/file`} target="_blank" rel="noreferrer">打开原卷</a><button disabled={locked} onClick={async()=>{await postJson(`/api/papers/${paperId}/analyze`,{});await onReload()}}>自动提取并交给 Agent</button><div className="number-strip">{list.map(q=><button key={q.id} onClick={()=>onNavigate(q.id,'diagnosis')}>第{q.number}题</button>)}</div>{selected&&<><h3><MathText text={selected.stem}/></h3>{selected.page_start&&<img className="evidence-image" src={`/api/questions/${selected.id}/evidence`} alt="初步切分区域"/>}</>}</section>
  const pending = probes.filter(p => !p.attempts.length).length
  return <div className="learning-workspace">
    <section className="panel loop-intro"><div className="eyebrow">真实试卷 · 首轮证据</div><h2>{paper?.title}</h2><p><MathText text={report.summary}/></p>
      <div className="loop-metrics"><span><b>{list.length}</b>题已定位</span><span><b>{list.filter(q=>q.correctness==='wrong').length}</b>题答案有误</span><span><b>{pending}</b>个检验环节待作答</span><span><b>待核定</b>总分</span></div>
      <small><MathText text={report.score_status}/></small>
    </section>
    <div className="loop-tabs">{[['diagnosis','原卷与诊断'],['probes','针对性检验'],['profile','初始画像']].map(([id,label])=><button key={id} className={tab===id?'filter active':'filter'} onClick={()=>setTab(id)}>{label}{id==='probes'&&` · ${pending}`}</button>)}</div>
    {tab==='diagnosis' && <>
      <div className="priority-grid">{report.priorities.map(p=><article className="panel" key={p.label}><span className="eyebrow">本轮优先</span><h3><MathText text={p.label}/></h3><p><MathText text={p.evidence}/></p><strong><MathText text={p.action}/></strong></article>)}</div>
      <div className="number-strip">{list.map(q=><button key={q.id} title={q.notes} className={`number-chip ${q.id===selected?.id?'selected':''} ${q.correctness}`} onClick={()=>onNavigate(q.id,'diagnosis')}>{q.number}<small>{({correct:'正确',wrong:'有误',partial:'部分完成',unknown:'待核实'} as Record<string,string>)[q.correctness]||'待核实'}</small></button>)}</div>
      {selected && diagnosis && <div className="evidence-columns"><section className="panel"><div className="eyebrow">原卷证据 · 第{selected.number}题</div><h3><MathText text={diagnosis.stem}/></h3>
        {diagnosis.regions.map((r,index)=><figure key={index}><img className="evidence-image" src={`/api/questions/${selected.id}/evidence?region=${index}`} alt={`第${selected.number}题原卷第${r.page}页区域${index+1}`} /><figcaption>原卷第{r.page}页 · {r.role==='supplemental_work'?'同题补充作答区域':'题目及作答区域'}</figcaption></figure>)}
        <a href={`/api/papers/${selected.paper_id}/file#page=${selected.page_start}`} target="_blank" rel="noreferrer">打开完整原卷</a>
      </section><section className="panel"><div className="eyebrow">观察与原因假设</div><p className="observation"><MathText text={diagnosis.observation}/></p>
        {diagnosis.hypotheses.map(h=><article className="hypothesis" key={h.id}><span className="status pending">原因待检验</span><h3><MathText text={h.label}/></h3><p><b>证据：</b><MathText text={h.evidence}/></p><p><b>还可能是：</b><MathText text={h.alternative}/></p><p><b>修正动作：</b><MathText text={h.correction}/></p></article>)}
        {!diagnosis.hypotheses.length&&<p>本题保留作答证据，暂不追加检验。</p>}
        <details key={`${selected.id}:reference`} onToggle={e=>toggle(`${selected.id}:参考结论与关键推导`,e.currentTarget.open)}><summary>参考结论与关键推导</summary><p><MathText text={diagnosis.reference_answer}/></p><p><MathText text={diagnosis.reference_reasoning}/></p></details>
        {diagnosis.grading_note&&<p className="muted"><MathText text={diagnosis.grading_note}/></p>}
        <details key={`${selected.id}:fingerprint`} onToggle={e=>toggle(`${selected.id}:这道题的指纹`,e.currentTarget.open)}><summary>这道题的指纹</summary><pre>{JSON.stringify(diagnosis.fingerprint,null,2)}</pre></details>
        {probes.some(p=>p.question_id===selected.id)&&<button className="primary full" onClick={()=>setTab('probes')}>进入针对性检验</button>}
      </section></div>}
    </>}
    {tab==='probes'&&<><section className="panel"><h2>每次检验一个明确环节</h2><p>按设置隐藏当前备考类别的检验题，点击确认后查看；其他类别直接显示。解析另行展开并记录。</p></section><div className="probe-list">{probes.map(p=><ProbeCard key={p.id} probe={p} locked={locked} onReload={onReload} onSelect={()=>setActiveProbe(p.id)} onAnalysis={open=>toggle(`${currentQuestion?.id}:检验解析`,open)}/>)}</div></>}
    {tab==='profile'&&<EvidenceProfile skills={loop.skills}/>}
    <details className="panel limitations" onToggle={e=>toggle('本轮识别边界与来源',e.currentTarget.open)}><summary>本轮识别边界与来源</summary><p>{report.author} · {report.method}</p>{report.limitations.map((x,i)=><p key={i}><MathText text={x}/></p>)}</details>
  </div>
}

function ProbeCard({probe,onReload,onSelect,locked,onAnalysis}:{probe:Probe;onReload:()=>Promise<void>;onSelect:()=>void;locked:boolean;onAnalysis:(open:boolean)=>void}){
  const photos=useAnswerImages('probe:'+probe.id),[response,setResponse]=useDraft('probe:'+probe.id+':text',''),[exposed,setExposed]=useDraft('probe:'+probe.id+':exposed',false),[requestId]=useDraft('probe:'+probe.id+':request',crypto.randomUUID())
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[supplement,setSupplement]=useState(false),[showAnalysis,setShowAnalysis]=useState(false)
  const last=probe.attempts.at(-1)
  const action=async(path:string,body:unknown)=>{setBusy(true);setError('');try{await postJson(path,body);await onReload();return true}catch(e){setError(String(e));return false}finally{setBusy(false)}}
  const submit=async()=>{const body={response,image_ids:photos.images.map(i=>i.id),answer_exposed:exposed||probe.bank_exposed,request_id:requestId};if(await action(last?`/api/attempts/${last.id}/supplement`:`/api/probes/${probe.id}/submit`,body)){setResponse('');photos.clear();setSupplement(false)}}
  return <article className="panel probe-card" tabIndex={0} onFocus={onSelect} onClick={onSelect}>
    {!probe.access.can_view?<BankGate item={probe.access} reload={onReload}/>:<><span className="eyebrow">数学{probe.access.math_type} · {probe.access.year} · 第{probe.access.number}题 · {probe.targets}</span><h3><MathText text={probe.skill_label}/></h3><p><b>为什么选这道题：</b><MathText text={probe.discriminates}/></p><img className="evidence-image" src={probe.question_image} alt="检验题原题图片"/><div className="probe-prompt"><MathText text={probe.prompt}/></div>
    {last&&<div className="attempt-result"><b>已保存的作答：</b><MathText text={last.response||'手写照片'}/><SubmittedImages ids={last.image_ids}/><p><MathText text={last.assessment?.feedback||'等待 Agent 核对；完成聊天回复不等于评价已写回。'}/></p>{(!last.assessment||last.assessment.correct===null)&&<button disabled={locked||busy} onClick={()=>action(`/api/probes/${probe.id}/feedback`,{attempt_id:last.id})}>请 Agent 继续核对并写回评价</button>}<button disabled={locked||busy} onClick={()=>setSupplement(!supplement)}>补充思路或局部照片</button><button disabled={locked||busy} onClick={()=>{const reason=prompt('你认为评价哪里有误？');if(reason)window.dispatchEvent(new CustomEvent('mathlens:discuss',{detail:`请核对作答 ${last.id} 的评价，用户反馈：${reason}。若需更正，用 revise_assessment 保留旧版本和修订原因。`}))}}>对评价提出异议</button><button disabled={locked||busy} onClick={()=>window.dispatchEvent(new CustomEvent('mathlens:discuss',{detail:`请重新审视检验 ${probe.id} 是否合适。若需要调整，请用 replace_probe 说明原因并保留旧作答。`}))}>请 Agent 调整检验</button></div>}
    {(!last||supplement)&&<fieldset disabled={locked||busy||photos.busy}><textarea aria-label={`${probe.skill_label}的作答`} placeholder={last?'补充缺少的步骤、重拍模糊部分；不必转录整页。':'写思路或上传手写作答照片'} value={response} onChange={e=>setResponse(e.target.value)} onPaste={e=>{if(e.clipboardData.files.length){e.preventDefault();photos.addFiles(Array.from(e.clipboardData.files))}}}/><AnswerImagePicker draft={photos} disabled={locked||busy}/>{!last&&<label><input type="checkbox" checked={exposed||probe.bank_exposed} disabled={probe.bank_exposed} onChange={e=>setExposed(e.target.checked)}/>此前看过这道题的答案或解析</label>}<button className="primary" disabled={!response.trim()&&!photos.images.length} onClick={submit}>{last?'保存补充并请 Agent 复核':'提交本环节作答'}</button></fieldset>}
    <details onToggle={e=>{setShowAnalysis(e.currentTarget.open);onAnalysis(e.currentTarget.open)}}><summary>参考与解析</summary>{probe.access.analysis_allowed?<><MathText text={probe.expected||''}/><MathText text={probe.solution_note||''}/>{showAnalysis&&<img className="evidence-image" src={probe.analysis_image} alt="原题参考解析"/>}</>:<><p>查看后会记录答案暴露，之后的回答不算独立检验。</p><button onClick={()=>action(`/api/bank/${probe.bank_id}/reveal`,{role:'analysis',confirmed:true})}>确认查看解析</button></>}</details></>}{error&&<p className="notice" role="alert">{error}</p>}</article>
}

export function EvidenceProfile({ skills }: { skills: Skill[] }) {
  return <section className="panel"><div className="eyebrow">按作答事件累计</div><h2>单卷画像，保留不确定性</h2><p>这里展示可追溯的证据数量。一次作答或一次检验不能证明稳定掌握；心态与耗时缺少资料时记为未知。</p><div className="skill-grid">{skills.map(s=><article className="skill-card" key={s.skill_id}><h3>{s.label}</h3><span className={`status ${s.failures?'pending':'done'}`}>{s.state}</span><p>原卷或检验有误 {s.failures} · 成功 {s.successes} · 待查 {s.pending}</p><small>来自 {s.papers} 张试卷 · 独立检验成功 {s.independent_probe_successes} 次</small></article>)}</div></section>
}
