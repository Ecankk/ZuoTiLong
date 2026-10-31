import {useEffect,useState} from 'react'
import {postJson} from './api'

type SavedPackage={sha256:string;document_sha256:string;imported_at:string}
type Listing={packages:SavedPackage[];current_release_id:string|null}
type Preview={sha256:string;nodes:number;atoms:number;sources:number;current_release_id:string|null}

export function CatalogPackages({locked,onReload}:{locked:boolean;onReload:()=>Promise<void>}){
  const [listing,setListing]=useState<Listing|null>(null),[preview,setPreview]=useState<Preview|null>(null)
  const [candidate,setCandidate]=useState<Record<string,unknown>|null>(null),[switchTo,setSwitchTo]=useState<SavedPackage|null>(null)
  const [busy,setBusy]=useState(false),[message,setMessage]=useState(''),[error,setError]=useState('')
  const load=async()=>{const r=await fetch('/api/knowledge/packages');if(!r.ok)throw new Error('无法读取通用目录版本');setListing(await r.json())}
  useEffect(()=>{load().catch(e=>setError(String(e)))},[])
  const choose=async(file:File)=>{
    setBusy(true);setError('');setMessage('');setPreview(null);setCandidate(null);setSwitchTo(null)
    try{
      if(file.size>16*1024*1024)throw new Error('目录文件不能超过 16 MB')
      const value=JSON.parse(await file.text())
      const result=await postJson<Preview>('/api/knowledge/packages/preview',{package:value})
      setCandidate(value);setPreview(result)
    }catch(e){setError(e instanceof Error?e.message:'无法读取目录文件')}
    finally{setBusy(false)}
  }
  const importNow=async()=>{
    if(!preview||!candidate)return
    setBusy(true);setError('')
    try{
      await postJson('/api/knowledge/packages/import',{package:candidate,trusted_sha256:preview.sha256,expected_active_release_id:preview.current_release_id,confirmed:true})
      setPreview(null);setCandidate(null);await load();await onReload();setMessage('通用考点目录已导入；已有试卷和作答保留')
    }catch(e){setError(e instanceof Error?e.message:'导入失败')}
    finally{setBusy(false)}
  }
  const activate=async()=>{
    if(!switchTo||!listing?.current_release_id)return
    setBusy(true);setError('')
    try{
      await postJson('/api/knowledge/packages/activate',{sha256:switchTo.sha256,expected_active_release_id:listing.current_release_id,confirmed:true})
      setSwitchTo(null);await load();await onReload();setMessage('目录版本已切换；原目录和学习记录仍保留')
    }catch(e){setError(e instanceof Error?e.message:'切换失败')}
    finally{setBusy(false)}
  }
  const download=async()=>{
    setBusy(true);setError('');setMessage('')
    try{
      const response=await fetch('/api/knowledge/packages/export')
      if(!response.ok){const value=await response.json();throw new Error(value.error||'暂时无法导出目录')}
      const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a')
      link.href=url;link.download='zuotilong-knowledge-catalog.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
      setMessage('已导出通用目录，不包含试卷、作答、画像或会话')
    }catch(e){setError(e instanceof Error?e.message:'导出失败')}
    finally{setBusy(false)}
  }
  return <section className="panel catalog-packages" aria-label="通用考点目录">
    <h2>通用考点目录</h2><p>导入已核对的通用目录，让新安装直接复用考点。它与个人试卷、作答和学习表现分开保存。</p>
    <div className="catalog-package-actions"><button disabled={busy} onClick={download}>导出通用目录</button><label className="catalog-package-file">选择目录文件<input aria-label="选择考点目录文件" type="file" accept="application/json,.json" disabled={busy} onChange={e=>{const f=e.target.files?.[0];e.target.value='';if(f)void choose(f)}}/></label></div>
    {busy&&<p role="status">正在核对目录资料，请稍候…</p>}
    {preview&&<div className="notice"><strong>待导入：{preview.atoms} 个原子考点 · {preview.nodes} 个目录节点 · {preview.sources} 个来源版本</strong><p>请使用你信任来源的目录文件。确认后切换通用目录，已有学习记录和旧目录保留；受影响的知识关联可能需要更新。</p><div className="catalog-package-actions"><button className="primary" disabled={locked||busy} onClick={importNow}>确认导入目录</button><button disabled={busy} onClick={()=>{setPreview(null);setCandidate(null)}}>取消导入</button></div></div>}
    {listing&&listing.packages.length>0&&<details><summary>已导入的目录版本（{listing.packages.length}）</summary><ul className="catalog-package-history">{listing.packages.map(p=><li key={p.sha256}><span><strong>目录版本 {p.sha256.slice(0,8)}</strong><small>导入于 {new Date(p.imported_at).toLocaleString()}</small></span>{listing.current_release_id===`catalog-${p.document_sha256}`?<span>当前使用</span>:<button disabled={locked||busy} onClick={()=>{setSwitchTo(p);setPreview(null);setCandidate(null);setError('')}}>使用此版本</button>}</li>)}</ul></details>}
    {switchTo&&<div className="notice"><p>切换到目录版本 {switchTo.sha256.slice(0,8)}？已有学习记录和版本历史保留，相关知识关联可能需要更新。</p><div className="catalog-package-actions"><button className="primary" disabled={locked||busy} onClick={activate}>确认切换目录</button><button disabled={busy} onClick={()=>setSwitchTo(null)}>取消切换</button></div></div>}
    {locked&&<p className="muted">本轮任务结束后可导入或切换；仍可查看、预览和导出。</p>}
    {message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
  </section>
}
