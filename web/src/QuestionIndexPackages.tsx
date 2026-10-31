import {useEffect,useState} from 'react'
import {postJson} from './api'

type SavedIndex={sha256:string;imported_at:string;enabled:number;local_records:number}
type IndexPreview={sha256:string;entries:number;matched_local_records:number;preview_sha256:string;omitted:Record<string,number>}
type Phase=''|'preview'|'import'|'export'|'state'
const omissionLabels:Record<string,string>={
  knowledge_mismatch:'考点定义或层级不匹配',
  local_material_unreadable:'本地材料暂不可读',
  conflicting_entries:'相同材料的标注存在分歧',
  already_reviewed_locally:'已有本机核验结果，保留原记录',
  already_imported:'已有可用共享标注',
}
const phaseLabels:Record<Exclude<Phase,''>,string>={
  preview:'正在核对本地题目与考点…',import:'正在保存匹配的标注…',
  export:'正在核对并导出就绪标注…',state:'正在更新索引状态…',
}

export function QuestionIndexPackages({locked,onReload}:{locked:boolean;onReload:()=>Promise<void>}){
  const [saved,setSaved]=useState<SavedIndex[]>([])
  const [preview,setPreview]=useState<IndexPreview|null>(null)
  const [candidate,setCandidate]=useState<Record<string,unknown>|null>(null)
  const [change,setChange]=useState<SavedIndex|null>(null)
  const [phase,setPhase]=useState<Phase>('')
  const [message,setMessage]=useState(''),[error,setError]=useState('')
  const busy=phase!==''
  const load=async()=>{
    const response=await fetch('/api/knowledge/question-index')
    if(!response.ok)throw new Error('无法读取已保存的题目标注索引')
    const value=await response.json() as {packages:SavedIndex[]}
    setSaved(value.packages)
  }
  useEffect(()=>{void load().catch(e=>setError(e instanceof Error?e.message:'读取失败'))},[])

  const choose=async(file:File)=>{
    setPhase('preview');setError('');setMessage('');setPreview(null);setCandidate(null);setChange(null)
    try{
      if(file.size>16*1024*1024)throw new Error('索引文件不能超过 16 MB')
      const value=JSON.parse(await file.text()) as Record<string,unknown>
      const result=await postJson<IndexPreview>('/api/knowledge/question-index/preview',{package:value})
      setCandidate(value);setPreview(result)
    }catch(e){setError(e instanceof Error?e.message:'无法读取索引文件')}
    finally{setPhase('')}
  }

  const importNow=async()=>{
    if(!candidate||!preview||locked||busy)return
    setPhase('import');setError('')
    try{
      const result=await postJson<{imported:number;reused:boolean}>('/api/knowledge/question-index/import',{
        package:candidate,trusted_sha256:preview.sha256,expected_preview_sha256:preview.preview_sha256,confirmed:true,
      })
      setCandidate(null);setPreview(null);await load();await onReload()
      setMessage(result.reused?'此索引已保存，无需重复导入':`已复用 ${result.imported} 条题目标注；未改动个人作答`)
    }catch(e){setError(e instanceof Error?e.message:'导入失败，请重新预览')}
    finally{setPhase('')}
  }

  const download=async()=>{
    setPhase('export');setError('');setMessage('')
    try{
      const response=await fetch('/api/knowledge/question-index/export')
      if(!response.ok){const value=await response.json();throw new Error(value.error||'无法导出标注索引')}
      const url=URL.createObjectURL(await response.blob()),link=document.createElement('a')
      link.href=url;link.download='zuotilong-question-index.json';link.click()
      setTimeout(()=>URL.revokeObjectURL(url),1000)
      setMessage('已导出标注索引；不包含题目正文、答案、推导或个人资料')
    }catch(e){setError(e instanceof Error?e.message:'导出失败')}
    finally{setPhase('')}
  }

  const updateState=async()=>{
    if(!change||locked||busy)return
    setPhase('state');setError('')
    try{
      await postJson('/api/knowledge/question-index/state',{sha256:change.sha256,enabled:!change.enabled,confirmed:true})
      setMessage(change.enabled?'已停用后续选题中的此索引；历史练习保留':'已重新启用此索引，材料和考点仍须匹配')
      setChange(null);await load();await onReload()
    }catch(e){setError(e instanceof Error?e.message:'无法更新索引状态')}
    finally{setPhase('')}
  }

  return <section className="panel catalog-packages" aria-label="通用题目标注索引">
    <h2>题目标注索引</h2>
    <p>在另一份本地资料库复用已核题目的考点与检验环节。请先准备相同题库和通用目录；题干、参考或考点定义不匹配时不会沿用。</p>
    <div className="catalog-package-actions">
      <button disabled={busy} onClick={download}>导出就绪标注索引</button>
      <label className="catalog-package-file">选择标注索引文件<input type="file" aria-label="选择题目标注索引文件" accept="application/json,.json" disabled={busy} onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void choose(file)}}/></label>
    </div>
    {phase&&<p role="status">{phaseLabels[phase]}</p>}
    {preview&&<div className="notice">
      <strong>{preview.entries} 条共享索引，本机新增匹配 {preview.matched_local_records} 条题目记录</strong>
      <p>请选择你信任来源的索引。这里核对内容散列，不代表本机重新进行数学审校；已有本机核验结果会保留。</p>
      {!!Object.keys(preview.omitted).length&&<ul>{Object.entries(preview.omitted).map(([key,count])=><li key={key}>{omissionLabels[key]||'未纳入本次导入'}：{count}</li>)}</ul>}
      {!preview.matched_local_records&&<p>当前没有新增匹配。仍可保存索引；补齐相同版本的本地材料后，可再次选择此文件核对。</p>}
      <div className="catalog-package-actions">
        <button className="primary" disabled={locked||busy} onClick={importNow}>信任此来源并导入</button>
        <button disabled={busy} onClick={()=>{setPreview(null);setCandidate(null)}}>取消导入</button>
      </div>
    </div>}
    {!!saved.length&&<details><summary>已保存的标注索引（{saved.length}）</summary>
      <ul className="catalog-package-history">{saved.map(item=><li key={item.sha256}>
        <span><strong>索引 {item.sha256.slice(0,8)}</strong><small>{item.local_records} 条匹配记录 · {item.enabled?'已启用':'已停用'}</small></span>
        <button disabled={locked||busy} onClick={()=>{setChange(item);setPreview(null);setCandidate(null)}}>{item.enabled?'停用此索引':'重新启用'}</button>
      </li>)}</ul>
    </details>}
    {change&&<div className="notice">
      <p>{change.enabled?'停用后，后续选题不再使用此索引；已布置练习及其材料仍保留。':'重新启用后，只复用当前材料和知识依赖仍匹配的标注。'}</p>
      <div className="catalog-package-actions"><button className="primary" disabled={locked||busy} onClick={updateState}>{change.enabled?'确认停用':'确认启用'}</button><button disabled={busy} onClick={()=>setChange(null)}>取消</button></div>
    </div>}
    {locked&&<p className="muted">任务结束后可导入或启停索引；仍可预览和导出。</p>}
    {message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
  </section>
}
