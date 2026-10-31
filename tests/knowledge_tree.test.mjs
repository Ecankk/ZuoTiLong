import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import {createRequire} from 'node:module'
import {fileURLToPath} from 'node:url'

const require=createRequire(new URL('../web/package.json',import.meta.url))
const ts=require('typescript'),React=require('react'),{renderToStaticMarkup}=require('react-dom/server')
const cache=new Map()
function load(filename){
  if(cache.has(filename))return cache.get(filename).exports
  const module={exports:{}};cache.set(filename,module)
  const code=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText
  const localRequire=name=>{
    if(!name.startsWith('.'))return require(name)
    const base=path.resolve(path.dirname(filename),name),file=['.tsx','.ts','.js'].map(ext=>base+ext).find(fs.existsSync)
    if(!file)throw new Error('Missing UI dependency: '+name)
    return load(file)
  }
  vm.runInNewContext(code,{module,exports:module.exports,require:localRequire},{filename})
  return module.exports
}
const root=fileURLToPath(new URL('../web/src/',import.meta.url))
const {knowledgeIndex,treeView,scopeEvidence,nodeKind,resolveKnowledgeId}=load(path.join(root,'knowledge-tree.ts'))
const {EvidenceProfile}=load(path.join(root,'EvidenceProfile.tsx'))
const {TopicTags}=load(path.join(root,'KnowledgeQuestions.tsx'))
const {KnowledgeTree}=load(path.join(root,'KnowledgeTree.tsx'))
function item(id,parent,kind,extra={}){
  return {skill_id:id,label:id,parent_id:parent,origin:{node_kind:kind},aliases:[],state:'未覆盖',
    failures:0,successes:0,pending:0,papers:0,independent_probe_successes:0,
    question_ids:[],probe_ids:[],events:[],original:[],tasks:[],hasRecords:false,...extra}
}
function fixture(){return [
  item('calculus',null,'subject',{label:'高等数学'}),
  item('integrals','calculus','chapter',{label:'多元积分'}),
  item('inertia','integrals','atom',{label:'定轴转动惯量',aliases:['轴惯量'],hasRecords:true}),
  item('mass','integrals','atom',{label:'质量积分'}),
  item('probability',null,'subject',{label:'概率统计'}),
  item('density','probability','atom',{label:'概率密度'})]
}
const sorted=set=>[...set].sort()

test('a recorded atom keeps its complete path, while unrelated unrecorded topics stay outside the filter',()=>{
  const index=knowledgeIndex(fixture()),view=treeView(index,true,'')
  assert.deepEqual(sorted(view.visible),['calculus','inertia','integrals'])
  assert.equal(nodeKind(index.items.get('integrals')),'chapter')
})

test('searching an alias finds a leaf with ancestors, and a chapter search includes its eligible children',()=>{
  const index=knowledgeIndex(fixture())
  const leaf=treeView(index,false,'轴惯量')
  assert.deepEqual(sorted(leaf.visible),['calculus','inertia','integrals'])
  assert.deepEqual(sorted(leaf.matches),['inertia'])
  assert.deepEqual(sorted(treeView(index,false,'多元积分').visible),['calculus','inertia','integrals','mass'])
  assert.equal(treeView(index,true,'概率密度').visible.size,0)
  assert.equal(treeView(index,false,'概率密度').visible.has('density'),true)
})

test('one original, shared exercise and observation are counted once across sibling atoms',()=>{
  const values=fixture(),question={id:'q1'},probe={id:'probe1'},event={id:'event1',kind:'incomplete',paper_id:'p1',created_at:'2026-01-01'}
  for(const id of ['inertia','mass'])Object.assign(values.find(v=>v.skill_id===id),{original:[question],tasks:[probe],events:[event],hasRecords:true})
  const scope=scopeEvidence(knowledgeIndex(values),'integrals')
  assert.equal(scope.original.length,1);assert.equal(scope.tasks.length,1);assert.equal(scope.events.length,1)
  assert.equal(scope.atoms,2);assert.equal(scope.recordedAtoms,2)
})

test('incomplete historical hierarchy remains reachable without recursive cycles or invented knowledge',()=>{
  const values=[item('a','b','atom'),item('b','a','atom'),item('orphan','missing','atom')]
  const index=knowledgeIndex(values)
  assert.equal(index.invalidHierarchy,true)
  assert.deepEqual([...index.roots].sort(),['a','b','orphan'])
  assert.equal(treeView(index,false,'').visible.size,3)
  assert.equal(scopeEvidence(index,'a').atoms,1)
})

function render({selected='inertia',protectedQuestion=false,group=false,noRecords=false,previousIds=[]}={}){
  const skills=fixture(),paper={id:'paper1',title:'隔离卷',math_type:1}
  const question={id:'q1',paper_id:'paper1',number:'1',correctness:'wrong'}
  const probe={id:'probe1',paper_id:'paper1',question_id:'q1',prompt:'HIDDEN_QUESTION_STEM',discriminates:'HIDDEN_QUESTION_DETAIL',attempts:[],
    access:{id:'bank1',math_type:1,year:'2020',number:7,can_view:!protectedQuestion,reserved:false,reason:'保留真题，确认后查看'}}
  for(const id of ['inertia','mass'])Object.assign(skills.find(s=>s.skill_id===id),{
    question_ids:noRecords?[]:['q1'],probe_ids:noRecords?[]:['probe1'],
    origin:{node_kind:'atom',definition:'I_L=∫dist(r,L)²dm',conditions:['质量非负且二阶矩有限。'],boundaries:['转轴与坐标平面不可混用。'],source_refs:[{source_id:'source-entry',source_version_id:'version-test'}]}})
  skills.find(s=>s.skill_id==='integrals').state='初步掌握'
  skills.find(s=>s.skill_id==='inertia').previous_ids=previousIds
  return renderToStaticMarkup(React.createElement(EvidenceProfile,{skills,papers:[paper],questions:[question],probes:[probe],
    selectedId:group?'integrals':selected,studyType:1,onReload:async()=>{},onOpen(){},locked:true}))
}

test('a selected atomic node exposes its exact definition, conditions, boundary and provenance',()=>{
  const html=render()
  for(const text of ['质量非负且二阶矩有限','转轴与坐标平面不可混用','source-entry','来源与版本'])assert.match(html,new RegExp(text))
  assert.doesNotMatch(html,/必要时细化目录/)
})

test('group navigation loads its read-only question query and never claims whole-chapter mastery',()=>{
  const html=render({group:true})
  assert.equal((html.match(/打开同一练习与作答/g)||[]).length,0)
  assert.match(html,/正在读取题目关联/)
  assert.match(html,/不据此判断整章掌握/)
  assert.doesNotMatch(html,/初步掌握/)
})

test('an unfinished protected true question exposes neither its prompt nor its diagnostic hint',()=>{
  const html=render({protectedQuestion:true})
  assert.match(html,/正在读取题目关联/)
  assert.doesNotMatch(html,/HIDDEN_QUESTION_STEM|HIDDEN_QUESTION_DETAIL/)
})

test('a catalogue without personal records is browsable and does not label it a weakness',()=>{
  const html=render({noRecords:true})
  assert.match(html,/全部题库/)
  assert.match(html,/暂无学习证据/)
  assert.doesNotMatch(html,/需要关注/)
})

test('a retired ID selects and searches the canonical node with its full ancestor path',()=>{
  const values=fixture();values.find(v=>v.skill_id==='inertia').previous_ids=['old.inertia-a','old.inertia_a']
  const index=knowledgeIndex(values)
  assert.equal(resolveKnowledgeId(index,'old.inertia-a'),'inertia')
  assert.equal(resolveKnowledgeId(index,'old.inertia_a'),'inertia')
  assert.equal(resolveKnowledgeId(index,'old.inertiaa'),'old.inertiaa')
  assert.equal(resolveKnowledgeId(index,'inertia'),'inertia')
  assert.equal(resolveKnowledgeId(index,'unknown'),'unknown')
  const found=treeView(index,false,'old.inertia-a')
  assert.deepEqual(sorted(found.matches),['inertia'])
  assert.deepEqual(sorted(found.visible),['calculus','inertia','integrals'])
  assert.deepEqual(values.find(v=>v.skill_id==='inertia').aliases,['轴惯量'])
})

test('retired-ID deep links show canonical evidence while keeping hidden question content protected',()=>{
  const html=render({selected:'old.inertia',previousIds:['old.inertia'],protectedQuestion:true})
  assert.match(html,/定轴转动惯量/)
  assert.match(html,/质量非负且二阶矩有限/)
  assert.match(html,/正在读取题目关联/)
  assert.doesNotMatch(html,/当前目录中未找到这个考点|HIDDEN_QUESTION_STEM|HIDDEN_QUESTION_DETAIL/)
  assert.match(render({selected:'truly.unknown'}),/当前目录中未找到这个考点/)
})

test('conflicting navigation metadata is not guessed and current IDs win over old IDs',()=>{
  const values=fixture()
  values.find(v=>v.skill_id==='inertia').previous_ids=['ambiguous','mass']
  values.find(v=>v.skill_id==='mass').previous_ids=['ambiguous']
  const index=knowledgeIndex(values)
  assert.equal(resolveKnowledgeId(index,'ambiguous'),'ambiguous')
  assert.equal(resolveKnowledgeId(index,'mass'),'mass')
  assert.equal(treeView(index,false,'ambiguous').matches.size,0)
})

test('question navigation has exactly the two agreed views and keeps the complete catalogue',()=>{
  const html=render({noRecords:true})
  assert.match(html,/aria-label="关联题目视图"/)
  assert.match(html,/>已完成题目<\/button>/)
  assert.match(html,/>全部题库<\/button>/)
  assert.doesNotMatch(html,/aria-label="考点范围"|>有记录<\/button>/)
  assert.match(html,/概率统计/)
})

test('node counts distinguish completed questions from bank coverage',()=>{
  const index=knowledgeIndex(fixture()),visible=new Set(index.items.keys())
  const props={index,visible,selected:'',query:'',onSelect:()=>{},counts:{calculus:{bank:17,completed:2}}}
  assert.match(renderToStaticMarkup(React.createElement(KnowledgeTree,{...props,questionView:'bank'})),/题库关联 17 题/)
  assert.match(renderToStaticMarkup(React.createElement(KnowledgeTree,{...props,questionView:'completed'})),/已完成 2 题/)
})

test('question tags show canonical names and mathematical roles without solution metadata',()=>{
  const html=renderToStaticMarkup(React.createElement(TopicTags,{topics:[
    {topic_id:'atom-1',name:'链式求导',role:'primary',stages:['formula']},
    {topic_id:'atom-2',name:'复合函数',role:'prerequisite',stages:['entry']}
  ],onSelect:()=>{}}))
  assert.match(html,/主要/);assert.match(html,/必要前置/);assert.match(html,/链式求导/)
  assert.doesNotMatch(html,/reference_reasoning|fingerprint|<img/)
})

test('retired-ID lookup respects current filters and does not restore obsolete aliases after an index refresh',()=>{
  const values=fixture();values.find(v=>v.skill_id==='density').previous_ids=['old.density']
  const index=knowledgeIndex(values)
  assert.equal(treeView(index,true,'old.density').visible.size,0)
  assert.equal(treeView(index,false,'old.density').matches.has('density'),true)
  assert.equal(resolveKnowledgeId(knowledgeIndex(fixture()),'old.density'),'old.density')
})
