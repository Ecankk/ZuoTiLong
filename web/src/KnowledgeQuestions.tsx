import {useEffect,useState} from 'react'
import {MathText} from './MathText'
import type {OpenEvidence} from './EvidenceProfile'

export type TopicTag={topic_id:string;name:string;role:string;stages:string[]}
export type LinkSource={bank_id?:string;source_kind?:'paper'|'probe';math_type?:number;year?:string;number?:number|string;source?:string;status?:string;reserved?:boolean;topics:TopicTag[];matched_topics?:TopicTag[];annotation_id?:string;annotation_origin?:string;paper_id?:string;paper_title?:string;question_id?:string;probe_id?:string;state?:string;date?:string;protected?:boolean;assisted?:boolean}
export type LinkPage={catalog_revision:string|null;navigation_revision:string;topic_id:string|null;view:string;total:number;source_records:number;offset:number;limit:number;next_offset:number|null;items:{entity_id:string;sources:LinkSource[]}[]}
export type LinkCount={bank:number;ready:number;completed:number;source_records:number}
export type LinkSummary={catalog_revision:string|null;navigation_revision:string;nodes:Record<string,LinkCount>;total_completed:number;total_bank:number;default_view:'completed'|'bank'}
export const roleName=(role:string)=>({primary:'主要',supporting:'辅助',prerequisite:'必要前置',coverage:'涉及考点'} as Record<string,string>)[role]||role
export const annotationName=(status?:string)=>({ready:'标注就绪',needs_review:'参考待核',needs_catalog:'考点待补',outdated:'标注已失效',unannotated:'尚未标注'} as Record<string,string>)[status||'']||'待核'

export async function readLinks<T>(url:string,signal?:AbortSignal):Promise<T>{
  const response=await fetch(url,{signal})
  if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||'无法读取题目关联')}
  return response.json()
}

export function TopicTags({topics,onSelect}:{topics:TopicTag[];onSelect:(id:string)=>void}){
  return <div className="topic-tags">{topics.map(t=><button key={t.topic_id} className={`topic-tag ${t.role}`} title={`${roleName(t.role)}考点 · ${t.topic_id}`} onClick={e=>{e.stopPropagation();onSelect(t.topic_id)}}><small>{roleName(t.role)}</small><MathText text={t.name}/></button>)}</div>
}

export function KnowledgeQuestions({topicId,questionView,offset=0,paperId,summary,onOffset,onTopic,onOpen,onBank,onRefreshSummary}:{topicId:string;questionView:'completed'|'bank';offset?:number;paperId?:string;summary?:LinkSummary;onView:(view:'completed'|'bank')=>void;onOffset:(offset:number)=>void;onTopic:(id:string)=>void;onOpen:OpenEvidence;onBank?:(id:string)=>void;onRefreshSummary?:()=>void}){
  const [page,setPage]=useState<LinkPage|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true)
  const catalogRevision=summary?.catalog_revision
  useEffect(()=>{
    const abort=new AbortController();setLoading(true);setError('');setPage(null)
    const q=new URLSearchParams({view:questionView,topic_id:topicId,scope:'subtree',offset:String(offset),limit:'12'})
    if(paperId)q.set('paper_id',paperId)
    if(catalogRevision)q.set('catalog_revision',catalogRevision)
    readLinks<LinkPage>('/api/knowledge/links?'+q,abort.signal).then(value=>{
      if(abort.signal.aborted)return
      if(summary&&value.navigation_revision!==summary.navigation_revision){onRefreshSummary?.();return}
      setPage(value)
    }).catch(e=>{if(!abort.signal.aborted){setError(String(e));if(String(e).includes('版本已更新'))onRefreshSummary?.()}}).finally(()=>{if(!abort.signal.aborted)setLoading(false)})
    return()=>abort.abort()
  },[topicId,questionView,offset,paperId,catalogRevision,summary?.navigation_revision])
  const count=summary?.nodes[topicId]
  return <section className="knowledge-related knowledge-question-links" aria-label="关联题目">
    <h3>{questionView==='completed'?'已完成题目':'全部题库'}</h3>
    {count&&<p className="link-counts">已完成 <b>{count.completed}</b> 题<span>题库关联 <b>{count.bank}</b> 题，其中 <b>{count.ready}</b> 题标注就绪</span></p>}
    <p className="muted">{questionView==='completed'?'原卷与补强保留各次作答入口；完成不等于答对。':'包含已做、预留和待核题。章节包含子考点，同题合并显示；点击浏览原题后才加载题目。'}</p>
    {loading&&<p role="status">正在读取题目关联…</p>}
    {error&&<p role="alert" className="notice">{error}</p>}
    {!loading&&!error&&!page?.items.length&&<div className="empty-state">{questionView==='completed'?'暂无已完成记录。这不代表该考点薄弱。':'当前范围暂无有效题库关联，不能据此判断个人能力。'}</div>}
    {page?.items.map(group=><article className="linked-question" key={group.entity_id}>
      {group.sources.map((source,i)=><div className="linked-question-source" key={source.bank_id+'|'+source.probe_id+'|'+source.question_id+'|'+i}>
        <div className="linked-question-heading"><strong>{questionView==='bank'?`数学${['','一','二','三'][source.math_type||0]||'类别待核'} · ${source.year||'年份待核'} · 第${source.number||'待核'}题`:`${source.paper_title} · ${source.source_kind==='paper'?'原卷':'补强'}第${source.number||'待核'}题`}</strong><span className="status neutral">{questionView==='bank'?annotationName(source.status):({correct:'已反馈 · 正确',wrong:'已反馈 · 有误',partial:'部分作答'} as Record<string,string>)[source.state||'']||'已完成'}</span></div>
        {source.reserved&&<small className="muted">已预留，仅供自主浏览，不用于选题</small>}
        {source.annotation_origin==='shared'&&<small className="muted">关联来自已接受的共享标注索引</small>}
        {source.date&&<small className="muted">{source.date.slice(0,10)}{source.assisted?' · 参考后完成':''}</small>}
        {!source.protected&&<TopicTags topics={source.topics} onSelect={onTopic}/>}
        {source.protected?<p className="muted">该练习仍按设置保护，进入原练习确认后查看。</p>:questionView==='bank'&&!source.topics.length&&<p className="muted">暂无当前有效原子标签。</p>}
        {questionView==='bank'?<button className="small-action" onClick={()=>source.bank_id&&onBank?.(source.bank_id)}>浏览原题</button>:<button className="small-action" onClick={()=>onOpen(source.paper_id!,source.question_id!,source.source_kind==='probe'?'probes':'diagnosis',source.probe_id)}>查看原记录</button>}
      </div>)}
      {group.sources.length>1&&<small className="muted">同一道题的 {group.sources.length} 条来源或作答记录</small>}
    </article>)}
    {page&&page.total>0&&<div className="link-pagination"><span>{page.total} 道题 · {page.source_records} 条来源／记录</span><button disabled={!offset||loading} onClick={()=>onOffset(Math.max(0,offset-12))}>上一页</button><span>第 {Math.floor(offset/12)+1} 页</span><button disabled={page.next_offset===null||loading} onClick={()=>onOffset(page.next_offset!)}>下一页</button></div>}
  </section>
}
