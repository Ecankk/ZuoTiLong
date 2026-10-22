import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import {createRequire} from 'node:module'

const require = createRequire(import.meta.url)
const ts = require('../web/node_modules/typescript')
const exports = {}
const code = ts.transpileModule(fs.readFileSync(new URL('../web/src/math.ts', import.meta.url),'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
vm.runInNewContext(code,{exports})
const {mathParts, renderMathPart} = exports
const katex = require('../dist/vendor/katex/katex.min.js')

test('multiline $$, dollar inline, bracket and parenthesis formulas render with actual KaTeX', () => {
  const parts = mathParts(String.raw`前文 $x^2$；$$
\begin{aligned} x&=1\\ y&=2\end{aligned}
$$；\[\frac{1}{2}\]；\(\sin t\) 后文`)
  const equations = parts.filter(p=>p.kind==='math')
  assert.equal(equations.length,4)
  assert.equal(equations.filter(p=>p.display).length,2)
  for (const part of equations) assert.match(renderMathPart(part,katex).html,/class="katex/)
})

test('unfinished streamed formulas remain intact until closed', () => {
  for (const source of ['$$\\frac{1}{', '$x+', '\\[x^2', '正文 $$x+1']) {
    const parts = mathParts(source)
    assert.equal(parts.map(p=>p.raw).join(''),source)
    assert.equal(parts.filter(p=>p.kind==='math').length,0)
  }
  assert.match(renderMathPart(mathParts('$$x+1$$')[0],katex).html,/katex-display/)
})

test('ordinary code and escaped dollars remain literal', () => {
  const source = '示例 `$$x$$`\n```python\ncost = "$5"\n```\n\\$10\n末尾$'
  const parts = mathParts(source)
  assert.equal(parts.filter(p=>p.kind==='math').length,0)
  assert.equal(parts.map(p=>p.raw).join(''),source)
})

test('AI latex fences render with and without extra math delimiters', () => {
  for (const body of [String.raw`\frac{1}{2}`,String.raw`$$\frac{1}{2}$$`]) {
    const parts = mathParts('```latex\n'+body+'\n```')
    assert.equal(parts.length,1)
    assert.match(renderMathPart(parts[0],katex).html,/katex-display/)
  }
})

test('unsupported formulas preserve their original source instead of disappearing', () => {
  const part = mathParts('$$\\unknowncommand{x}$$')[0]
  assert.equal(renderMathPart(part,katex).error,true)
  assert.equal(part.raw,'$$\\unknowncommand{x}$$')
})

test('rendering does not allow executable hrefs or raw HTML', () => {
  const part = mathParts(String.raw`$$\href{javascript:alert(1)}{x}$$`)[0]
  const rendered = renderMathPart(part,katex)
  assert.doesNotMatch(rendered.html||'',/<a\s|href="javascript:/)
  const raw = '<img src=x onerror=alert(1)>'
  assert.equal(mathParts(raw)[0].kind,'text')
  assert.equal(renderMathPart(mathParts(raw)[0],katex).html,undefined)
})
