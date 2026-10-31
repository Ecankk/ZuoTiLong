import {useEffect,useState} from 'react'
import type {BankQuestion,VisibleContext} from './types'
import {MathText} from './MathText'
import {TopicTags,annotationName,readLinks,type LinkPage,type LinkSource} from './KnowledgeQuestions'

const names=['','一','二','三']
type Props={bank:BankQuestion[];onContextChange:(c:VisibleContext)=>void;bankId?:string;topicId?:string;category?:string;year?:string;offset?:number;onNavigate?:(next:{bankId?:string;topic?:string;category?:string;year?:string;offset?:number})=>void;onTopic?:(id:string)=>void}

export function LibraryBrowser({bank,onContextChange,bankId='',topicId='',category='',year='',offset=0,onNavigate,onTopic}:Props){
  const [page,setPage]=useState<LinkPage|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[topics,setTopics]=useState<LinkSource>()
  const [local,setLocal]=useState({category,year,offset,bankId})
  const choice=onNavigate?{category,year,offset,bankId}:local
  const navigate=(next:Partial<typeof local>)=>{setLocal(before=>({...before,...next}));onNavigate?.(next)}
  const selected=bank.find(b=>b.id===choice.bankId)
  useEffect(()=>{
    const abort=new AbortController();setError('');setPage(null);setLoading(true);setTopics(undefined)
    const q=new URLSearchParams({view:'bank',limit:'15',offset:String(choice.offset)})
    if(choice.category)q.set('math_type',choice.category)
    if(choice.year)q.set('year',choice.year)
    if(topicId)q.set('topic_id',topicId)
    const url=choice.bankId?'/api/bank/'+encodeURIComponent(choice.bankId)+'/topics':'/api/knowledge/links?'+q
    readLinks<LinkPage|{items:LinkSource[]}>(url,abort.signal).then(value=>{
      if(abort.signal.aborted)return
      if(choice.bankId)setTopics((value as {items:LinkSource[]}).items[0]);else setPage(value as LinkPage)
    }).catch(e=>{if(!abort.signal.aborted)setError(String(e))}).finally(()=>{if(!abort.signal.aborted)setLoading(false)})
    return()=>abort.abort()
  },[choice.category,choice.year,choice.offset,choice.bankId,topicId])
  const select=(item:BankQuestion)=>onContextChange({view:'本地题库',label:`${item.year} 数学${names[item.math_type]} 第 ${item.number} 题`,bank_id:item.id,section:'题库直接浏览'})
  const openTopic=(id:string)=>onTopic?onTopic(id):location.assign('/?view=knowledge&question_view=bank&topic='+encodeURIComponent(id))
  return <>
    <section className="panel">
      <h2>本地题库</h2><p>数学一、二、三均可直接浏览。原子标签来自现有标注，点击可查看对应考点。</p>
      <div className="library-toolbar"><div className="segmented" role="group" aria-label="题库类别"><button aria-pressed={!choice.category} className={!choice.category?'active':''} onClick={()=>navigate({category:'',offset:0,bankId:''})}>全部 <small>{bank.length}</small></button>{[1,2,3].map(n=><button key={n} aria-pressed={choice.category===String(n)} className={choice.category===String(n)?'active':''} onClick={()=>navigate({category:String(n),offset:0,bankId:''})}>数学{names[n]} <small>{bank.filter(b=>b.math_type===n).length}</small></button>)}</div><label className="library-year">年份<input aria-label="题库年份" placeholder="如 2025" value={choice.year} onChange={e=>navigate({year:e.target.value,offset:0,bankId:''})}/></label></div>
      {topicId&&<p>已按考点筛选 <button onClick={()=>onNavigate?.({topic:'',offset:0})}>清除考点筛选</button></p>}
      {choice.bankId&&<button onClick={()=>navigate({bankId:''})}>返回题库列表</button>}
      {loading&&<p role="status">正在读取题库与原子标签…</p>}{error&&<p className="notice" role="alert">{error}</p>}
      {!choice.bankId&&page&&<div className="link-pagination"><span>{page.total} 道题 · {page.source_records} 条来源</span><button disabled={!choice.offset} onClick={()=>navigate({offset:Math.max(0,choice.offset-15)})}>上一页</button><span>第 {Math.floor(choice.offset/15)+1} 页</span><button disabled={page.next_offset===null} onClick={()=>navigate({offset:page.next_offset!})}>下一页</button></div>}
      {!loading&&!error&&!choice.bankId&&!page?.items.length&&<p>当前范围还没有题目，请调整类别、年份或考点。</p>}
    </section>
    {choice.bankId?(selected?<LibraryCard key={selected.id} item={selected} tags={topics} onSelect={()=>select(selected)} onTopic={openTopic}/>:<p>没有找到这道题，原题可能已移出当前题库。</p>):<div className="cards">{page?.items.map(group=>{
      const source=group.sources[0],item=bank.find(b=>b.id===source.bank_id)
      return item&&<div key={group.entity_id}><LibraryCard item={item} tags={source} onSelect={()=>select(item)} onTopic={openTopic}/>{group.sources.length>1&&<details className="library-aliases"><summary>同题的其他来源（{group.sources.length-1}）</summary>{group.sources.slice(1).map(s=><button key={s.bank_id} onClick={()=>navigate({bankId:s.bank_id})}>数学{names[s.math_type||0]} {s.year} 第{s.number}题 · {annotationName(s.status)}</button>)}</details>}</div>
    })}</div>}
  </>
}

function LibraryCard({item,tags,onSelect,onTopic}:{item:BankQuestion;tags?:LinkSource;onSelect:()=>void;onTopic:(id:string)=>void}){
  const [analysis,setAnalysis]=useState(false)
  return <article className="card" tabIndex={0} onFocus={onSelect} onClick={onSelect}>
    <div className="linked-question-heading"><strong>数学{names[item.math_type]} · {item.year} · 第 {item.number} 题</strong><span className="status neutral">{tags?annotationName(tags.status):'正在读取标注'}</span></div>
    {item.reserved&&<p className="muted">已预留，不用于 Agent 选题</p>}
    {tags?.topics.length?<TopicTags topics={tags.topics} onSelect={onTopic}/>:tags&&<p className="muted">暂无当前有效原子标签；不影响自主浏览。</p>}
    {tags?.annotation_origin==='shared'&&<small className="muted">关联来自已接受的共享标注索引</small>}
    <MathText text={item.stem||''}/>
    {item.question_image&&<img className="evidence-image" loading="lazy" src={item.question_image} alt={`数学${names[item.math_type]} ${item.year} 第${item.number}题`}/>}
    <details onToggle={e=>setAnalysis(e.currentTarget.open)}><summary>查看解析</summary><p className="muted">查看后会记录答案曝光。</p>{analysis&&item.analysis_image&&<img className="evidence-image" src={item.analysis_image} alt="题目解析"/>}</details>
  </article>
}
