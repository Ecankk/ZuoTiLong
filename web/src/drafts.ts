import { useEffect, useState,useRef } from 'react'

export function useDraft<T>(key:string, initial:T) {
  const storage='mathlens:draft:'+key
  const [value,setValue]=useState<T>(()=>{try{return JSON.parse(localStorage.getItem(storage)||'null')??initial}catch{return initial}})
  const [ready,setReady]=useState(false),edited=useRef(false),hadLocal=useRef(localStorage.getItem(storage)!==null)
  useEffect(()=>{let live=true;fetch('/api/drafts?key='+encodeURIComponent(key)).then(r=>r.json()).then(data=>{if(live&&!edited.current&&!hadLocal.current&&data.value!==undefined)setValue(data.value)}).catch(()=>{}).finally(()=>{if(live)setReady(true)});return()=>{live=false}},[key])
  useEffect(()=>{try{localStorage.setItem(storage,JSON.stringify(value))}catch{/* Current draft remains in memory. */}if(!ready)return;const t=setTimeout(()=>fetch('/api/drafts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key,value})}).catch(()=>{}),250);return()=>clearTimeout(t)},[storage,key,value,ready])
  return [value,(next:typeof value|((old:T)=>T))=>{edited.current=true;setValue(next)}] as const
}
