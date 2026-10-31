import {useEffect,useState} from 'react'
import {postJson} from './api'
import type {Preferences} from './types'

export function AgentPrompt({preferences,locked,onReload,onSaving}:{preferences:Preferences;locked:boolean;onReload:()=>Promise<void>;onSaving:(saving:boolean)=>void}){
  const [editing,setEditing]=useState(false),[draft,setDraft]=useState(preferences.paper_marking_convention),[busy,setBusy]=useState(false),[message,setMessage]=useState('')
  useEffect(()=>{if(!editing)setDraft(preferences.paper_marking_convention)},[preferences.paper_marking_convention,editing])
  const save=async()=>{
    setBusy(true);onSaving(true);setMessage('')
    try{await postJson('/api/preferences/agent-prompt',{prompt:draft});await onReload();setEditing(false);setMessage('已保存，从下一轮生效')}
    catch(error){setMessage(error instanceof Error?error.message:'保存失败，请重试')}
    finally{setBusy(false);onSaving(false)}
  }
  return <section className="agent-prompt" aria-label="Agent 默认提示词">
    <div className="prompt-heading"><strong>默认提示词</strong>{!editing&&<button className="small-action" disabled={locked||busy} onClick={()=>{setDraft(preferences.paper_marking_convention);setMessage('');setEditing(true)}}>修改</button>}</div>
    {editing?<><label>每轮请求都会附带<textarea aria-label="Agent 默认提示词内容" value={draft} maxLength={1000} disabled={locked||busy} onChange={e=>setDraft(e.target.value)}/></label><div className="prompt-actions"><button className="primary" disabled={locked||busy} onClick={save}>{busy?'保存中…':'保存提示词'}</button><button disabled={locked||busy} onClick={()=>setDraft(preferences.default_agent_prompt)}>恢复默认</button><button disabled={busy} onClick={()=>{setEditing(false);setMessage('')}}>取消</button></div><small>保存后从下一轮生效。留空将使用默认提示词。</small></>:<p className="prompt-preview">{preferences.paper_marking_convention}</p>}
    {locked&&<small>连接或本轮处理完成后可修改</small>}
    {message&&<p className="prompt-message" role="status">{message}</p>}
  </section>
}
