import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import {createRequire} from 'node:module'

const require=createRequire(import.meta.url)
const ts=require('../web/node_modules/typescript')
const exports={}
const code=ts.transpileModule(fs.readFileSync(new URL('../web/src/agent-state.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
vm.runInNewContext(code,{exports})
const {mergeAgentState}=exports

test('fresh and pre-versioned snapshots keep updating instead of freezing',()=>{
  const first={status:'disconnected'},next={status:'connecting'}
  assert.equal(mergeAgentState(null,first),first)
  assert.equal(mergeAgentState(first,next),next)
  assert.equal(mergeAgentState(first,{revision:1,status:'idle'}).status,'idle')
})

test('whole-snapshot order handles durable jobs independently of session revision',()=>{
  const before={revision:10,snapshot_epoch:'server-a',snapshot_sequence:3,preparation:'running'}
  const after={revision:10,snapshot_epoch:'server-a',snapshot_sequence:4,preparation:'paused'}
  assert.equal(mergeAgentState(before,after),after)
  assert.equal(mergeAgentState(after,before),after)
})

test('restarted server may restore a lower revision without freezing the page',()=>{
  const old={revision:99,snapshot_epoch:'server-a',snapshot_sequence:40}
  const next={revision:3,snapshot_epoch:'server-b',snapshot_sequence:1}
  assert.equal(mergeAgentState(old,next),next)
  assert.equal(mergeAgentState({revision:4},{revision:3}).revision,4)
})
