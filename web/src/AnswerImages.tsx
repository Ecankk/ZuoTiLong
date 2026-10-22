import { useState } from 'react'

export type AnswerImage = {id:string; url:string; width:number; height:number}

export function useAnswerImages() {
  const [images,setImages] = useState<AnswerImage[]>([])
  const [busy,setBusy] = useState(false)
  const [error,setError] = useState('')
  const addFiles = async (files: File[]) => {
    if (!files.length || busy) return
    if (files.length + images.length > 4 || files.some(f=>f.size>8*1024*1024)) {setError('每次最多 4 张照片，每张不超过 8 MB');return}
    setBusy(true);setError('')
    try {
      const form = new FormData()
      files.forEach(file=>form.append('files',file))
      const response = await fetch('/api/answer-images',{method:'POST',body:form})
      const result = await response.json()
      if (!response.ok) throw new Error(result.error || '图片上传失败')
      setImages(old=>[...new Map([...old,...result.images].map((image:AnswerImage)=>[image.id,image])).values()])
    } catch(e) {setError(e instanceof Error?e.message:'图片上传失败，请重试')}
    finally {setBusy(false)}
  }
  return {images,busy,error,addFiles,clear:()=>{setImages([]);setError('')},remove:(id:string)=>setImages(old=>old.filter(image=>image.id!==id)),move:(id:string,delta:number)=>setImages(old=>{
    const index=old.findIndex(image=>image.id===id), next=index+delta
    if(index<0||next<0||next>=old.length)return old
    const images=[...old];[images[index],images[next]]=[images[next],images[index]];return images
  })}
}

export function AnswerImagePicker({draft,disabled=false}:{draft:ReturnType<typeof useAnswerImages>;disabled?:boolean}) {
  const blocked=disabled||draft.busy
  return <div className="answer-image-picker">
    <div className="image-actions"><label className="small-action">选择作答照片<input aria-label="选择作答照片" type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={blocked} onChange={e=>{draft.addFiles(Array.from(e.target.files||[]));e.target.value=''}}/></label>
      <label className="small-action">拍照<input aria-label="拍摄作答照片" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" disabled={blocked} onChange={e=>{draft.addFiles(Array.from(e.target.files||[]));e.target.value=''}}/></label>
      <small className="muted">{draft.busy?'正在上传…':'最多 4 张，JPG / PNG / WebP；可不填文字'}</small></div>
    <div className="answer-image-grid">{draft.images.map((image,index)=><figure key={image.id}><a href={image.url} target="_blank" rel="noreferrer"><img src={image.url} alt={`待提交作答照片 ${index+1}`}/></a><figcaption>第 {index+1} 张 <button type="button" className="small-action" disabled={blocked||index===0} onClick={()=>draft.move(image.id,-1)}>上移</button> <button type="button" className="small-action" disabled={blocked||index===draft.images.length-1} onClick={()=>draft.move(image.id,1)}>下移</button> <button type="button" className="small-action" disabled={blocked} onClick={()=>draft.remove(image.id)}>移除</button></figcaption></figure>)}</div>
    {draft.error&&<p className="notice" role="alert">{draft.error}</p>}
  </div>
}

export function SubmittedImages({ids=[]}:{ids?:string[]}) {
  return <div className="answer-image-grid">{ids.map((id,index)=><a key={id} href={`/api/answer-images/${id}`} target="_blank" rel="noreferrer"><img src={`/api/answer-images/${id}`} alt={`已提交手写作答 ${index+1}`}/></a>)}</div>
}
