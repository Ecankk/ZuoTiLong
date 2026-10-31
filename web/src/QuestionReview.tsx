import {useState} from 'react'
import {postJson} from './api'
import {useDraft} from './drafts'
import {AnswerImagePicker,SubmittedImages,useAnswerImages} from './AnswerImages'

export type QuestionReviewRecord={question_id:string;report_id:string;note:string;image_ids:string[];image_roles:Record<string,string>;status:string;created_at:string;error?:string}

export function QuestionReview({questionId,reportId,number,unresolved,locked,records,onReload}:{questionId:string;reportId:string;number:string;unresolved:boolean;locked:boolean;records:QuestionReviewRecord[];onReload:()=>Promise<void>}){
  const key=`question-review:${questionId}:${reportId}`
  const photos=useAnswerImages(key)
  const [note,setNote]=useDraft(key+':note','')
  const [requestId,setRequestId]=useDraft(key+':request',crypto.randomUUID())
  const [busy,setBusy]=useState(false),[message,setMessage]=useState('')
  const latest=records.find(r=>r.question_id===questionId)
  const submit=async()=>{
    setBusy(true);setMessage('')
    try{
      await postJson(`/api/questions/${questionId}/review`,{report_id:reportId,request_id:requestId,note,
        image_ids:photos.images.map(i=>i.id),image_roles:Object.fromEntries(photos.images.map(i=>[i.id,i.role||'own_work']))})
      setNote('');photos.clear();setRequestId(crypto.randomUUID())
      setMessage('本题复核已排入，说明和照片已保存；连接就绪后继续。整卷核对通过后将自动准备练习。')
      window.dispatchEvent(new Event('mathlens:agent-refresh'));await onReload()
    }catch(e){setMessage(e instanceof Error?e.message:'本题复核未能排入，请重试')}
    finally{setBusy(false)}
  }
  return <section className="question-review">
    <h3>{unresolved?'本题需要重新核对':'对本题分析有疑问？'}</h3>
    <p>助手会重读原页与放大局部。可直接复核，无需转录答案；旧分析和其他题保留。</p>
    <fieldset disabled={locked||busy||photos.busy}>
      <details><summary>可选：补充说明或局部照片</summary>
        <textarea aria-label={`第${number}题复核说明`} maxLength={4000} placeholder="可指出要复看的位置；不填也能提交。" value={note} onChange={e=>setNote(e.target.value)} onPaste={e=>{if(e.clipboardData.files.length){e.preventDefault();photos.addFiles(Array.from(e.clipboardData.files))}}}/>
        <AnswerImagePicker draft={photos} disabled={locked||busy} label="选择原题局部照片"/>
      </details>
      <button className={unresolved?'primary':'small-action'} onClick={submit}>{busy?'正在保存…':'重新核对本题'}</button>
    </fieldset>
    {message&&<p className="notice" role="status">{message}</p>}
    {latest&&<details><summary>已保存的本题复核材料 · {new Date(latest.created_at).toLocaleString()}</summary>
      <p>{latest.note||'未附加说明，使用原卷复核。'}</p><SubmittedImages ids={latest.image_ids} roles={latest.image_roles}/>
      {latest.error&&<p className="notice">{latest.error}</p>}
    </details>}
  </section>
}
