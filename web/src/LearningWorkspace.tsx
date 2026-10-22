import { useEffect, useState } from 'react'
import { postJson } from './api'
import type { Paper, Question } from './types'

declare global { interface Window { katex?: { renderToString: (input: string, options: Record<string, unknown>) => string } } }

export type Diagnosis = {
  number: number; stem: string; correctness: string; observation: string; reference_answer: string;
  reference_reasoning: string; grading_note?: string; hypotheses: { id: string; label: string; evidence: string; alternative: string; correction: string }[];
  regions: { page: number; bbox: number[]; role: string }[]; fingerprint: Record<string, unknown>
}
export type Probe = {
  id: string; paper_id: string; question_id: string; bank_id: string; skill_id: string; skill_label: string;
  prompt: string; targets: string; discriminates: string; expected?: string; solution_note?: string;
  status: string; priority: number; question_image: string; analysis_image: string; bank_exposed: boolean;
  attempts: { id: string; response: string; answer_exposed: number; assessment?: { correct: boolean; feedback: string } }[]
}
export type Skill = { skill_id: string; label: string; failures: number; successes: number; pending: number; papers: number; state: string; independent_probe_successes: number }
export type Loop = { reports: { id: string; paper_id: string; summary: string; limitations: string[]; author: string; method: string; score_status: string; priorities: { label: string; evidence: string; action: string }[] }[];
  diagnoses: Record<string, Diagnosis>; probes: Probe[]; skills: Skill[] }

export function MathText({ text }: { text: string }) {
  const parts = text.split(/(\$\$[\s\S]*?\$\$|\$[^$\n]+\$)/g)
  return <span className="math-text">{parts.map((part, i) => {
    if (part.startsWith('$') && window.katex) {
      const display = part.startsWith('$$'); const input = part.slice(display ? 2 : 1, display ? -2 : -1)
      return <span key={i} dangerouslySetInnerHTML={{ __html: window.katex.renderToString(input, { throwOnError: false, trust: false, displayMode: display, strict: 'ignore' }) }} />
    }
    return <span key={i}>{part}</span>
  })}</span>
}

export function LearningWorkspace({ loop, questions, papers, onReload, focusedQuestion }: { loop: Loop; questions: Question[]; papers: Paper[]; onReload: () => Promise<void>; focusedQuestion?: Question }) {
  const [paperId, setPaperId] = useState(loop.reports[0]?.paper_id || '')
  const [tab, setTab] = useState('diagnosis')
  const [selectedNumber, setSelectedNumber] = useState('7')
  useEffect(()=>{if(focusedQuestion){setPaperId(focusedQuestion.paper_id);setSelectedNumber(focusedQuestion.number);setTab('diagnosis')}},[focusedQuestion])
  const report = loop.reports.find(r => r.paper_id === paperId) || loop.reports[0]
  if (!report) return null
  const paper = papers.find(p => p.id === report.paper_id)
  const list = questions.filter(q => q.paper_id === report.paper_id).sort((a,b) => Number(a.number)-Number(b.number))
  const selected = list.find(q => q.number === selectedNumber) || list[0]
  const diagnosis = selected && loop.diagnoses[selected.id]
  const probes = loop.probes.filter(p => p.paper_id === report.paper_id)
  const pending = probes.filter(p => !p.attempts.length).length
  return <div className="learning-workspace">
    <section className="panel loop-intro"><div className="eyebrow">真实试卷 · 首轮证据</div><h2>{paper?.title}</h2><p>{report.summary}</p>
      <div className="loop-metrics"><span><b>{list.length}</b>题已定位</span><span><b>{list.filter(q=>q.correctness==='wrong').length}</b>题答案有误</span><span><b>{pending}</b>个检验环节待作答</span><span><b>待核定</b>总分</span></div>
      {loop.reports.length > 1 && <select value={report.paper_id} onChange={e=>setPaperId(e.target.value)}>{loop.reports.map(r=><option key={r.id} value={r.paper_id}>{papers.find(p=>p.id===r.paper_id)?.title}</option>)}</select>}
      <small>{report.score_status}</small>
    </section>
    <div className="loop-tabs">{[['diagnosis','原卷与诊断'],['probes','针对性检验'],['profile','初始画像']].map(([id,label])=><button key={id} className={tab===id?'filter active':'filter'} onClick={()=>setTab(id)}>{label}{id==='probes'&&` · ${pending}`}</button>)}</div>
    {tab==='diagnosis' && <>
      <div className="priority-grid">{report.priorities.map(p=><article className="panel" key={p.label}><span className="eyebrow">本轮优先</span><h3>{p.label}</h3><p>{p.evidence}</p><strong>{p.action}</strong></article>)}</div>
      <div className="number-strip">{list.map(q=><button key={q.id} title={q.notes} className={`number-chip ${q.id===selected?.id?'selected':''} ${q.correctness}`} onClick={()=>setSelectedNumber(q.number)}>{q.number}<small>{({correct:'正确',wrong:'有误',partial:'部分完成',unknown:'待核实'} as Record<string,string>)[q.correctness]||'待核实'}</small></button>)}</div>
      {selected && diagnosis && <div className="evidence-columns"><section className="panel"><div className="eyebrow">原卷证据 · 第{selected.number}题</div><h3><MathText text={diagnosis.stem}/></h3>
        {diagnosis.regions.map((r,index)=><figure key={index}><img className="evidence-image" src={`/api/questions/${selected.id}/evidence?region=${index}`} alt={`第${selected.number}题原卷第${r.page}页区域${index+1}`} /><figcaption>原卷第{r.page}页 · {r.role==='supplemental_work'?'同题补充作答区域':'题目及作答区域'}</figcaption></figure>)}
        <a href={`/api/papers/${selected.paper_id}/file#page=${selected.page_start}`} target="_blank" rel="noreferrer">打开完整原卷</a>
      </section><section className="panel"><div className="eyebrow">观察与原因假设</div><p className="observation">{diagnosis.observation}</p>
        {diagnosis.hypotheses.map(h=><article className="hypothesis" key={h.id}><span className="status pending">原因待检验</span><h3>{h.label}</h3><p><b>证据：</b>{h.evidence}</p><p><b>还可能是：</b>{h.alternative}</p><p><b>修正动作：</b>{h.correction}</p></article>)}
        {!diagnosis.hypotheses.length&&<p>本题保留作答证据，暂不追加检验。</p>}
        <details><summary>参考结论与关键推导</summary><p><MathText text={diagnosis.reference_answer}/></p><p><MathText text={diagnosis.reference_reasoning}/></p></details>
        {diagnosis.grading_note&&<p className="muted">{diagnosis.grading_note}</p>}
        <details><summary>这道题的指纹</summary><pre>{JSON.stringify(diagnosis.fingerprint,null,2)}</pre></details>
        {probes.some(p=>p.question_id===selected.id)&&<button className="primary full" onClick={()=>setTab('probes')}>进入针对性检验</button>}
      </section></div>}
    </>}
    {tab==='probes'&&<><section className="panel"><h2>先做优先检验，每次只回答一个环节</h2><p>题目来自已导入的数学一真题库。这里只改变回答范围，保留原题条件。尚未作答的任务不计入画像；提交后才显示参考答案。</p></section><div className="probe-list">{probes.filter(p=>p.priority===1).map(p=><ProbeCard key={p.id} probe={p} onReload={onReload}/>)}</div><details className="panel"><summary>其他待查问题 · {probes.filter(p=>p.priority!==1).length} 个环节</summary><div className="probe-list">{probes.filter(p=>p.priority!==1).map(p=><ProbeCard key={p.id} probe={p} onReload={onReload}/>)}</div></details></>}
    {tab==='profile'&&<EvidenceProfile skills={loop.skills}/>}
    <details className="panel limitations"><summary>本轮识别边界与来源</summary><p>{report.author} · {report.method}</p>{report.limitations.map((x,i)=><p key={i}>{x}</p>)}</details>
  </div>
}

function ProbeCard({ probe, onReload }: { probe: Probe; onReload: () => Promise<void> }) {
  const [response,setResponse]=useState('');const [exposed,setExposed]=useState(false);const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [showAnalysis,setShowAnalysis]=useState(false);const [requestId]=useState(()=>crypto.randomUUID())
  const submit=async()=>{setBusy(true);setError('');try{await postJson(`/api/probes/${probe.id}/submit`,{response,answer_exposed:exposed||probe.bank_exposed,request_id:requestId});setResponse('');await onReload()}catch(e){setError(e instanceof Error?e.message:'提交失败')}finally{setBusy(false)}}
  const last=probe.attempts.at(-1)
  return <article className="panel probe-card"><span className="eyebrow">{probe.bank_id.replace('math1-','数学一 ')} · {probe.targets}</span><h3>{probe.skill_label}</h3><p>{probe.discriminates}</p>
    <img className="evidence-image" src={probe.question_image} alt="检验题原题图片"/>
    <div className="probe-prompt"><MathText text={probe.prompt}/></div>
    {last?<div className="attempt-result"><b>你的作答：</b><MathText text={last.response}/><p>{last.assessment?.feedback||'已保存，等待 Agent 核对表达与推导；暂不判错。'}</p><details onToggle={e=>setShowAnalysis(e.currentTarget.open)}><summary>查看本环节参考与原题解析</summary><p><MathText text={probe.expected||''}/></p><p><MathText text={probe.solution_note||''}/></p>{showAnalysis&&<img className="evidence-image" src={probe.analysis_image} alt="原题参考解析"/>}</details></div>:
    <><textarea aria-label={`${probe.skill_label}的作答`} placeholder="写出这一步的结果或思路；不知道也可以如实写下。" value={response} onChange={e=>setResponse(e.target.value)}/><label className="check-label"><input type="checkbox" checked={exposed||probe.bank_exposed} disabled={probe.bank_exposed} onChange={e=>setExposed(e.target.checked)}/>{probe.bank_exposed?'已在本系统查看该题解析，本次记为有提示的练习':'此前看过这道题的答案或解析'}</label><button className="primary" disabled={busy||!response.trim()} onClick={submit}>{busy?'保存中…':'提交本环节作答'}</button></>}
    {error&&<p role="alert" className="notice">{error}</p>}
  </article>
}

export function EvidenceProfile({ skills }: { skills: Skill[] }) {
  return <section className="panel"><div className="eyebrow">按作答事件累计</div><h2>单卷画像，保留不确定性</h2><p>这里展示可追溯的证据数量。一次作答或一次检验不能证明稳定掌握；心态与耗时缺少资料时记为未知。</p><div className="skill-grid">{skills.map(s=><article className="skill-card" key={s.skill_id}><h3>{s.label}</h3><span className={`status ${s.failures?'pending':'done'}`}>{s.state}</span><p>原卷或检验有误 {s.failures} · 成功 {s.successes} · 待查 {s.pending}</p><small>来自 {s.papers} 张试卷 · 独立检验成功 {s.independent_probe_successes} 次</small></article>)}</div></section>
}
