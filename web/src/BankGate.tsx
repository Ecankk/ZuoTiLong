import {useState} from 'react'
import {postJson} from './api'
import type {BankQuestion} from './types'

export function BankGate({item,reload}:{item:Pick<BankQuestion,'id'|'math_type'|'year'|'number'|'reserved'|'reason'>;reload:()=>Promise<void>}){
  const [confirm,setConfirm]=useState(false),[error,setError]=useState('')
  return <div className="bank-gate"><strong>数学{['?','一','二','三'][item.math_type]} · {item.year||'年份待核'} · 第 {item.number||'?'} 题</strong><div className="hidden-question" aria-label="题干尚未加载">题目内容尚未加载</div><p>{item.reason}</p>{!item.reserved&&(confirm?<><p>查看后会记录题干曝光，可能影响后续整卷自测。</p><button className="primary" onClick={async()=>{try{await postJson(`/api/bank/${item.id}/reveal`,{role:'question',confirmed:true});await reload()}catch(e){setError(String(e))}}}>确认查看这道真题</button><button className="small-action" onClick={()=>setConfirm(false)}>暂不查看</button></>:<button className="small-action" onClick={()=>setConfirm(true)}>查看题目…</button>)}{error&&<p role="alert">{error}</p>}</div>
}
