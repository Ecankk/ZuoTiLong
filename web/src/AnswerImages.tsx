import { useState,useEffect,useRef } from 'react'
import {useDraft} from './drafts'
import {postJson} from './api'

export type AnswerImage = {id:string; url:string; width:number; height:number}

export function useAnswerImages(key='agent') {
  const [images,setImages] = useDraft<AnswerImage[]>(key+':images',[])
  const [busy,setBusy] = useState(false)
  const [error,setError] = useState('')
  const [mobile,setMobile]=useState<string[]>([]),seen=useRef(new Set<string>())
  useEffect(()=>{if(!mobile.length)return;const timer=setInterval(async()=>{try{const state=await(await fetch('/api/mobile-upload/state')).json();if(!state.active||state.target!==key){setMobile([]);return}const incoming:AnswerImage[]=state.images.filter((i:AnswerImage)=>!seen.current.has(i.id));incoming.forEach(i=>seen.current.add(i.id));if(incoming.length)setImages(old=>[...new Map([...old,...incoming].map(i=>[i.id,i])).values()].slice(0,4))}catch{}},1500);return()=>clearInterval(timer)},[mobile.length,key])
  const startMobile=async()=>{if(!window.confirm('临时开启仅接收照片的局域网端口，10 分钟后关闭。请仅在可信 Wi-Fi 使用；链接可上传照片，不能访问试卷或 Agent。'))return;try{seen.current.clear();const result=await postJson<{urls:string[]}>('/api/mobile-upload/start',{target:key,confirmed:true});setMobile(result.urls)}catch(e){setError(String(e))}}
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
  return {images,busy,error,addFiles,mobile,startMobile,stopMobile:async()=>{await postJson('/api/mobile-upload/stop',{});setMobile([])},clear:()=>{setImages([]);setError('');if(mobile.length){postJson('/api/mobile-upload/stop',{}).catch(()=>{});setMobile([])}},remove:(id:string)=>setImages(old=>old.filter(image=>image.id!==id)),move:(id:string,delta:number)=>setImages(old=>{
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
    <button type="button" className="small-action" disabled={blocked} onClick={draft.startMobile}>从手机传图…</button>{!!draft.mobile.length&&<div className="notice"><p>手机和电脑连接同一 Wi-Fi，打开任一地址。收到的照片会进入这里的预览；请在电脑确认提交。</p>{draft.mobile.map(url=><p key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></p>)}<button type="button" onClick={draft.stopMobile}>关闭手机传图</button></div>}
    <div className="answer-image-grid">{draft.images.map((image,index)=><figure key={image.id}><a href={image.url} target="_blank" rel="noreferrer"><img src={image.url} alt={`待提交作答照片 ${index+1}`}/></a><figcaption>第 {index+1} 张 <button type="button" className="small-action" disabled={blocked||index===0} onClick={()=>draft.move(image.id,-1)}>上移</button> <button type="button" className="small-action" disabled={blocked||index===draft.images.length-1} onClick={()=>draft.move(image.id,1)}>下移</button> <button type="button" className="small-action" disabled={blocked} onClick={()=>draft.remove(image.id)}>移除</button></figcaption></figure>)}</div>
    {draft.error&&<p className="notice" role="alert">{draft.error}</p>}
  </div>
}

export function SubmittedImages({ids=[]}:{ids?:string[]}) {
  return <div className="answer-image-grid">{ids.map((id,index)=><a key={id} href={`/api/answer-images/${id}`} target="_blank" rel="noreferrer"><img src={`/api/answer-images/${id}`} alt={`已提交手写作答 ${index+1}`}/></a>)}</div>
}
