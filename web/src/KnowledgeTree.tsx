import {useEffect,useRef,useState} from 'react'
import {MathText} from './MathText'
import {ancestorIds,nodeKind,scopeEvidence,type KnowledgeIndex} from './knowledge-tree'

export const kindLabel=(kind:string)=>({subject:'学科',chapter:'章节',topic:'大考点',atom:'原子考点'} as Record<string,string>)[kind]||'考点'

export function KnowledgeTree({index,visible,selected,query,onSelect,counts,questionView}:{index:KnowledgeIndex;visible:Set<string>;selected:string;query:string;onSelect:(id:string)=>void;counts?:Record<string,{bank:number;completed:number}>;questionView?:'completed'|'bank'}){
  const [expanded,setExpanded]=useState(()=>new Set(index.roots)),[searchClosed,setSearchClosed]=useState(new Set<string>())
  const selectedRow=useRef<HTMLButtonElement>(null)
  const selectedPath=JSON.stringify(ancestorIds(index,selected))
  const selectionVisible=visible.has(selected)
  useEffect(()=>{setSearchClosed(new Set())},[query])
  useEffect(()=>{
    if(!selected||!selectionVisible)return
    const path=JSON.parse(selectedPath) as string[]
    setExpanded(before=>new Set([...before,...path]))
    setSearchClosed(before=>new Set([...before].filter(id=>!path.includes(id))))
    const frame=requestAnimationFrame(()=>{
      selectedRow.current?.scrollIntoView({block:'nearest'})
      selectedRow.current?.closest('.knowledge-panel')?.scrollIntoView({block:'start'})
    })
    return()=>cancelAnimationFrame(frame)
  },[selected,selectedPath,selectionVisible])
  const toggle=(id:string)=>{
    const update=(before:Set<string>)=>{const next=new Set(before);next.has(id)?next.delete(id):next.add(id);return next}
    if(query.trim())setSearchClosed(update);else setExpanded(update)
  }
  const all=(open:boolean)=>{
    setExpanded(new Set(open?[...index.children.keys()]:[]))
    setSearchClosed(new Set(open?[]:[...index.children.keys()]))
  }
  const row=(id:string,depth:number)=>{
    if(!visible.has(id))return null
    const item=index.items.get(id)!,children=(index.children.get(id)||[]).filter(child=>visible.has(child))
    const open=query.trim()?!searchClosed.has(id):expanded.has(id),kind=nodeKind(item),stats=scopeEvidence(index,id)
    return <li key={id}>
      <div className={`knowledge-node ${selected===id?'selected':''}`} style={{paddingLeft:8+depth*16}}>
        {children.length?<button className="knowledge-toggle" aria-label={`${open?'收起':'展开'} ${item.label}`} aria-expanded={open} onClick={()=>toggle(id)}><span aria-hidden="true">{open?'▾':'▸'}</span></button>:<span className="knowledge-leaf" aria-hidden="true">·</span>}
        <button ref={selected===id?selectedRow:undefined} className="knowledge-select" aria-pressed={selected===id} onClick={()=>onSelect(id)}><span><MathText text={item.label}/></span><small>{counts?.[id]?`${questionView==='completed'?'已完成':'题库关联'} ${counts[id][questionView||'bank']} 题`:kind==='atom'?'正在读取关联':`${kindLabel(kind)} · ${stats.atoms} 原子`}</small></button>
      </div>
      {!!children.length&&open&&<ul>{children.map(child=>row(child,depth+1))}</ul>}
    </li>
  }
  return <div className="knowledge-navigation"><div className="knowledge-tree-actions"><span>按目录逐层展开</span><div><button onClick={()=>all(true)}>展开全部</button><button onClick={()=>all(false)}>收起全部</button></div></div><nav aria-label="考点目录" className="knowledge-nodes"><ul>{index.roots.map(id=>row(id,0))}</ul></nav>{index.invalidHierarchy&&<p className="muted">部分目录层级待核，已保留相关条目。</p>}</div>
}
