import type {Skill,Probe} from './LearningWorkspace'
import type {Question} from './types'

export type KnowledgeItem=Skill & {original:Question[];tasks:Probe[];hasRecords:boolean}
export type KnowledgeIndex={items:Map<string,KnowledgeItem>;redirects:Map<string,string>;children:Map<string,string[]>;parents:Map<string,string>;roots:string[];invalidHierarchy:boolean}

export function nodeKind(item:Skill){
  return item.origin?.node_kind||({concept:'atom'} as Record<string,string>)[item.scope_level||'']||item.scope_level||(item.parent_id?'atom':'subject')
}

export function knowledgeIndex(items:KnowledgeItem[]):KnowledgeIndex{
  const byId=new Map(items.map(item=>[item.skill_id,item])),parents=new Map<string,string>(),children=new Map<string,string[]>()
  const redirects=new Map<string,string>(),ambiguous=new Set<string>()
  for(const item of items)for(const oldId of item.previous_ids||[]){
    if(!oldId||byId.has(oldId)||ambiguous.has(oldId))continue
    const existing=redirects.get(oldId)
    if(existing&&existing!==item.skill_id){redirects.delete(oldId);ambiguous.add(oldId)}
    else redirects.set(oldId,item.skill_id)
  }
  let invalidHierarchy=false
  for(const item of items){
    if(!item.parent_id)continue
    const seen=new Set([item.skill_id]);let id:string|undefined=item.parent_id,valid=true
    while(id){if(seen.has(id)||!byId.has(id)){valid=false;break}seen.add(id);id=byId.get(id)?.parent_id||undefined}
    if(!valid){invalidHierarchy=true;continue}
    parents.set(item.skill_id,item.parent_id)
    const siblings=children.get(item.parent_id)||[];siblings.push(item.skill_id);children.set(item.parent_id,siblings)
  }
  return {items:byId,redirects,parents,children,roots:items.filter(item=>!parents.has(item.skill_id)).map(item=>item.skill_id),invalidHierarchy}
}

export function resolveKnowledgeId(index:KnowledgeIndex,id:string){
  return index.items.has(id)?id:index.redirects.get(id)||id
}

export function ancestorIds(index:KnowledgeIndex,id:string){
  const path:string[]=[];let parent=index.parents.get(id)
  while(parent){path.unshift(parent);parent=index.parents.get(parent)}
  return path
}

export function descendantIds(index:KnowledgeIndex,id:string):string[]{
  const found:string[]=[]
  for(const child of index.children.get(id)||[]){found.push(child,...descendantIds(index,child))}
  return found
}

export function treeView(index:KnowledgeIndex,onlyRecorded:boolean,query:string){
  const eligible=new Set<string>()
  for(const item of index.items.values()){
    if(onlyRecorded&&!item.hasRecords)continue
    eligible.add(item.skill_id)
    for(const parent of ancestorIds(index,item.skill_id))eligible.add(parent)
  }
  const term=query.trim().toLocaleLowerCase(),visible=new Set<string>(),matches=new Set<string>()
  if(!term)return {visible:eligible,matches}
  for(const id of eligible){
    const item=index.items.get(id)!
    const previousIds=(item.previous_ids||[]).filter(oldId=>index.redirects.get(oldId)===id)
    if(![item.label,id,...(item.aliases||[]),...previousIds].some(text=>text.toLocaleLowerCase().includes(term)))continue
    matches.add(id);visible.add(id)
    for(const parent of ancestorIds(index,id))visible.add(parent)
    for(const child of descendantIds(index,id))if(eligible.has(child))visible.add(child)
  }
  return {visible,matches}
}

export function scopeEvidence(index:KnowledgeIndex,id:string){
  const ids=[id,...descendantIds(index,id)],questions=new Map<string,Question>(),probes=new Map<string,Probe>()
  const events=new Map<string,NonNullable<Skill['events']>[number]>()
  let atoms=0,recordedAtoms=0
  for(const key of ids){
    const item=index.items.get(key);if(!item)continue
    if(nodeKind(item)==='atom'){atoms++;if(item.hasRecords)recordedAtoms++}
    for(const q of item.original)questions.set(q.id,q)
    for(const p of item.tasks)probes.set(p.id,p)
    for(const event of item.events||[]){
      const identity=event.id||[event.kind,event.paper_id,event.question_id||'',event.probe_id||'',event.created_at].join('|')
      events.set(identity,event)
    }
  }
  return {atoms,recordedAtoms,original:[...questions.values()],tasks:[...probes.values()],events:[...events.values()].sort((a,b)=>a.created_at.localeCompare(b.created_at))}
}
