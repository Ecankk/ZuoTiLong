import {useEffect,useState} from 'react'
import type {BankQuestion,VisibleContext} from './types'
import {MathText} from './MathText'

const names=['','一','二','三']

export function LibraryBrowser({bank,onContextChange}:{bank:BankQuestion[];onContextChange:(c:VisibleContext)=>void}){
  const [category,setCategory]=useState(''),[year,setYear]=useState(''),[page,setPage]=useState(0)
  const list=bank.filter(b=>(!category||String(b.math_type)===category)&&(!year||b.year.includes(year)))
  useEffect(()=>{onContextChange({view:'本地题库',label:`类别 ${category||'全部'} · 年份 ${year||'全部'} · 第 ${page+1} 页`,section:`类别=${category||'全部'};年份=${year||'全部'};页=${page+1}`})},[category,year,page,onContextChange])
  return <>
    <section className="panel">
      <h2>本地题库</h2>
      <p>数学一、二、三均可直接浏览。试卷中的针对性检验按设置隐藏当前备考类别的题目。</p>
      <select aria-label="题库类别" value={category} onChange={e=>{setCategory(e.target.value);setPage(0)}}>
        <option value="">全部类别（{bank.length} 题）</option>
        {[1,2,3].map(n=><option key={n} value={n}>数学{names[n]}（{bank.filter(b=>b.math_type===n).length} 题）</option>)}
      </select>
      <input aria-label="题库年份" placeholder="年份" value={year} onChange={e=>{setYear(e.target.value);setPage(0)}}/>
      <p>{list.length} 道题 · 第 {page+1} / {Math.max(1,Math.ceil(list.length/15))} 页 <button disabled={!page} onClick={()=>setPage(page-1)}>上一页</button><button disabled={(page+1)*15>=list.length} onClick={()=>setPage(page+1)}>下一页</button></p>
      {!list.length&&<p>当前范围还没有题目，请调整类别或年份。</p>}
    </section>
    <div className="cards">{list.slice(page*15,page*15+15).map(b=><LibraryCard key={b.id} item={b} onSelect={()=>onContextChange({view:'本地题库',label:`${b.year} 数学${names[b.math_type]} 第 ${b.number} 题`,bank_id:b.id,section:'题库直接浏览'})}/>)}</div>
  </>
}

function LibraryCard({item,onSelect}:{item:BankQuestion;onSelect:()=>void}){
  const [analysis,setAnalysis]=useState(false)
  return <article className="card" tabIndex={0} onFocus={onSelect} onClick={onSelect}>
    <strong>数学{names[item.math_type]} · {item.year} · 第 {item.number} 题</strong>
    {item.reserved&&<p className="muted">已预留，不用于 Agent 选题</p>}
    <MathText text={item.stem||''}/>
    <img className="evidence-image" loading="lazy" src={item.question_image} alt={`数学${names[item.math_type]} ${item.year} 第${item.number}题`}/>
    <details onToggle={e=>setAnalysis(e.currentTarget.open)}><summary>查看解析</summary><p className="muted">查看后会记录答案曝光。</p>{analysis&&<img className="evidence-image" src={item.analysis_image} alt="题目解析"/>}</details>
  </article>
}
