import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import {createRequire} from 'node:module'
import {fileURLToPath} from 'node:url'

const require=createRequire(new URL('../web/package.json',import.meta.url))
const ts=require('typescript'),React=require('react')
const {renderToStaticMarkup}=require('react-dom/server')
const cache=new Map()
function load(filename){
  if(cache.has(filename))return cache.get(filename).exports
  const module={exports:{}};cache.set(filename,module)
  const code=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{
    module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,
  }}).outputText
  const localRequire=name=>{
    if(!name.startsWith('.'))return require(name)
    const base=path.resolve(path.dirname(filename),name)
    const resolved=['.tsx','.ts','.js'].map(ext=>base+ext).find(file=>fs.existsSync(file))
    if(!resolved)throw new Error('Missing UI dependency: '+name)
    return load(resolved)
  }
  vm.runInNewContext(code,{module,exports:module.exports,require:localRequire},{filename})
  return module.exports
}
const {PracticeWorkspace}=load(fileURLToPath(new URL('../web/src/PracticeWorkspace.tsx',import.meta.url)))
function render(attempts,blocked,selectedProbeId='',overrides={}){
  const probe={id:'old-probe',paper_id:'paper-test',is_current:false,review_reason:'原题版本待核，原记录保留。',
    attempts,access:{math_type:1,year:'2020',number:1},...overrides}
  return renderToStaticMarkup(React.createElement(PracticeWorkspace,{
    goals:[],probes:[probe],allProbes:[probe],papers:[],selectedGoalId:'',selectedProbeId,
    blocked,message:'本卷练习',limitations:[],onSelectGoal(){},onOriginal(){},onRelated(){},
    renderProbe:item=>React.createElement('article',{key:item.id,'data-probe':item.id},'保留同一原记录'),
  }))
}

test('an unattempted legacy exercise remains reachable when its original version is unproved',()=>{
  const html=render([],false)
  assert.match(html,/原题版本待核的历史练习/)
  assert.match(html,/data-probe="old-probe"/)
  assert.equal((html.match(/data-probe="old-probe"/g)||[]).length,1)
})

test('old attempts are shown once even while the current paper is blocked',()=>{
  const html=render([{id:'old-attempt',response:'original saved work',assessment:null}],true)
  assert.match(html,/原题版本待核的历史练习/)
  assert.equal((html.match(/data-probe="old-probe"/g)||[]).length,1)
  assert.doesNotMatch(html,/历史作答与反馈/)
})

test('a profile deep link opens its saved exercise even without a current goal binding',()=>{
  const html=render([],false,'old-probe',{is_current:true,review_reason:undefined})
  assert.match(html,/data-probe="old-probe"/)
  assert.match(html,/返回全部考点/)
  assert.doesNotMatch(html,/尚未关联到当前目标/)
})

test('a profile deep link expands the historical record while preserving its review restriction',()=>{
  const html=render([],false,'old-probe')
  assert.match(html,/<details class="panel practice-history" open="">/)
  assert.match(html,/原题版本待核的历史练习/)
  assert.equal((html.match(/data-probe="old-probe"/g)||[]).length,1)
})
