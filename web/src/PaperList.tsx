import {useState} from 'react'
import type {Bootstrap,Paper} from './types'
import {archivePaper,restorePaper,resummarizePaper,uploadPaper,postJson} from './api'

export function formatTime(value?:string){
  if(!value)return '—'
  const date=new Date(value)
  return Number.isNaN(date.valueOf())?value:date.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})
}
type Operation={kind:'archive'|'restore'|'resummarize';paper:Paper}

export function PaperList({data,locked,reload,select}:{data:Bootstrap;locked:boolean;reload:()=>Promise<void>;select:(id:string)=>void}){
  const [file,setFile]=useState<File|null>(null),[title,setTitle]=useState(''),[examDate,setExamDate]=useState(()=>{
    const date=new Date();return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`
  })
  const [message,setMessage]=useState(''),[busy,setBusy]=useState(false),[archived,setArchived]=useState(false)
  const [operation,setOperation]=useState<Operation|null>(null),[scoring,setScoring]=useState<Paper|null>(null)
  const list=data.papers.filter(p=>Boolean(p.archived_at)===archived)
  const upload=async()=>{
    if(!file)return
    setBusy(true);setMessage('')
    try{const result=await uploadPaper(file,title||file.name.replace(/\.pdf$/i,''),examDate);if(result.analysis_warning)setMessage(result.analysis_warning);await reload();select(result.paper.id)}
    catch(error){setMessage(String(error))}finally{setBusy(false)}
  }
  const run=async()=>{
    if(!operation)return
    setBusy(true);setMessage('')
    try{
      const {kind,paper}=operation
      if(kind==='archive')await archivePaper(paper.id)
      else if(kind==='restore')await restorePaper(paper.id)
      else await resummarizePaper(paper.id)
      await reload();setOperation(null)
      setMessage(kind==='archive'?'试卷已归档，原卷与作答仍保留，可在已归档列表恢复。':kind==='restore'?'试卷已恢复，证据重新纳入当前画像。':'已交给 Agent 重新总结，现有报告保留到新版本写回。')
    }catch(error){setMessage(String(error))}finally{setBusy(false)}
  }
  return <>
    <section className="panel paper-import">
      <div><div className="eyebrow">导入已完成试卷</div><h2>从一份真实作答开始</h2><p>原卷、逐题诊断与后续检验归属于同一份试卷，时间和修订记录保留。</p></div>
      <fieldset disabled={locked||busy} className="paper-upload-form">
        <label className="file-picker">选择 PDF<input aria-label="已完成的试卷 PDF" type="file" accept="application/pdf" onChange={e=>setFile(e.target.files?.[0]||null)}/></label>
        <label>试卷名称<input aria-label="试卷名称" placeholder="如：2026 数学一" value={title} onChange={e=>setTitle(e.target.value)}/></label>
        <label>作答日期<input aria-label="作答日期" type="date" value={examDate} onChange={e=>setExamDate(e.target.value)}/></label>
        <button className="primary" disabled={!file} onClick={upload}>{busy?'正在处理…':'上传并开始分析'}</button>
      </fieldset>
      {busy&&<p role="status">正在上传并读取原卷，切分页数会显示在任务状态中；原始 PDF 会先保存在本机。</p>}
    </section>
    <div className="section-toolbar"><div><h2>{archived?'已归档试卷':'我的试卷'}</h2><p>{list.length} 份 · {archived?'恢复后继续学习与统计':'按作答日期排列'}</p></div><div className="segmented" role="group" aria-label="试卷范围"><button aria-pressed={!archived} className={!archived?'active':''} onClick={()=>setArchived(false)}>学习中</button><button aria-pressed={archived} className={archived?'active':''} onClick={()=>setArchived(true)}>已归档</button></div></div>
    {message&&<p className="notice" role="status">{message}</p>}
    {!list.length&&<section className="panel empty-state">{archived?'还没有归档试卷。':'上传已完成的 PDF，开始第一轮诊断。'}</section>}
    <div className="cards paper-cards">{list.map(p=>{
      const report=data.loop.reports.find(r=>r.paper_id===p.id)
      const status=report?'已诊断':p.import_status==='segmented'?'已初步切分':p.import_status==='needs_review'?'识别待核对':'待分析'
      return <article className="card paper-card" key={p.id}>
        <div className="paper-card-meta"><span>{p.exam_date||'作答日期未填'} · {p.page_count||'—'} 页</span><span className={`status ${report?'done':'pending'}`}>{archived?'已归档':status}</span></div>
        <button className="paper-open" onClick={()=>select(p.id)}><h3>{p.title}</h3><span>打开原卷与诊断 →</span></button>
        <div className="paper-score"><strong>{p.score_confirmed_at?p.score:'—'}</strong><span>/ {p.total_score||150} · {p.score_confirmed_at?'用户已核分':'总分待核定'}</span></div>
        <p className="paper-timestamps">导入 {formatTime(p.created_at)} · 更新 {formatTime(p.updated_at||p.analyzed_at||p.created_at)}</p>
        <div className="paper-actions">{archived?<button className="small-action" disabled={locked||busy} onClick={()=>setOperation({kind:'restore',paper:p})}>恢复试卷</button>:<><button className="small-action" disabled={locked||busy} onClick={()=>setScoring(p)}>核定总分</button><button className="small-action" disabled={locked||busy} onClick={()=>setOperation({kind:'resummarize',paper:p})}>重新总结</button><button className="small-action quiet" disabled={locked||busy} onClick={()=>setOperation({kind:'archive',paper:p})}>归档…</button></>}</div>
      </article>
    })}</div>
    {operation&&<div className="modal-overlay"><section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="paper-operation-title"><span className="eyebrow">请确认操作范围</span><h2 id="paper-operation-title">{operation.kind==='archive'?'归档这份试卷？':operation.kind==='restore'?'恢复这份试卷？':'重新总结这份试卷？'}</h2><strong>{operation.paper.title}</strong><p>{operation.kind==='archive'?'这份试卷将从默认列表和当前画像统计中移除。PDF、历史报告、照片及真实作答保留，之后可以恢复。':operation.kind==='restore'?'恢复后重新出现在学习列表，已有证据重新纳入画像统计。':'Agent 将汇总已经保存的逐题分析和练习反馈，保留旧总结、诊断与真实作答；需要先连接 Codex。'}</p><div className="dialog-actions"><button disabled={busy} onClick={()=>setOperation(null)}>取消</button><button className="primary" disabled={locked||busy} onClick={run}>{busy?'处理中…':operation.kind==='archive'?'确认归档':operation.kind==='restore'?'确认恢复':'确认重新总结'}</button></div></section></div>}
    {scoring&&<ScoreDialog paper={scoring} defaultType={data.preferences.study_type} disabled={locked} close={()=>setScoring(null)} saved={async()=>{setScoring(null);await reload();setMessage('核定分数已保存，可在个人画像查看成绩变化。')}}/>}
  </>
}

function ScoreDialog({paper,defaultType,disabled,close,saved}:{paper:Paper;defaultType:number;disabled:boolean;close:()=>void;saved:()=>Promise<void>}){
  const [score,setScore]=useState(paper.score_confirmed_at?String(paper.score):''),[total,setTotal]=useState(String(paper.total_score||150)),[category,setCategory]=useState(paper.math_type||defaultType),[busy,setBusy]=useState(false),[error,setError]=useState('')
  return <div className="modal-overlay"><form className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="paper-score-title" onSubmit={async e=>{e.preventDefault();setBusy(true);try{await postJson(`/api/papers/${paper.id}/score`,{score:Number(score),total_score:Number(total),math_type:category,confirmed:true});await saved()}catch(error){setError(String(error))}finally{setBusy(false)}}}><h2 id="paper-score-title">核定本卷总分</h2><p>{paper.title}</p><p>请根据批改结果填写。成绩变化只使用核定分数，缺失分数不会按 0 分统计。</p><label>数学类别<select aria-label="本卷数学类别" value={category} onChange={e=>setCategory(Number(e.target.value))}>{[1,2,3].map(n=><option value={n} key={n}>数学{['','一','二','三'][n]}</option>)}</select></label><div className="score-fields"><label>得分<input aria-label="核定得分" type="number" min="0" max={total} step="any" required value={score} onChange={e=>setScore(e.target.value)}/></label><label>满分<input aria-label="试卷满分" type="number" min="1" max="1000" required value={total} onChange={e=>setTotal(e.target.value)}/></label></div>{error&&<p role="alert">{error}</p>}<div className="dialog-actions"><button type="button" disabled={busy} onClick={close}>取消</button><button className="primary" disabled={disabled||busy||score===''}>确认保存核定分数</button></div></form></div>
}
