import katex from 'katex'
import { assert, test } from 'vitest'
import { mathParts, renderMathPart, type MathPart } from './math'

const html = (part: MathPart) => renderMathPart(part, katex).html ?? ''

// Ported from the former tests/math_render.test.mjs; runs against the bundled KaTeX.
test('missing report text does not crash formula rendering', () => {
  for (const value of [null, undefined, '']) assert.equal(mathParts(value).length, 0)
})

test('multiline $$, dollar inline, bracket and parenthesis formulas render with actual KaTeX', () => {
  const parts = mathParts(String.raw`前文 $x^2$；$$
\begin{aligned} x&=1\\ y&=2\end{aligned}
$$；\[\frac{1}{2}\]；\(\sin t\) 后文`)
  const equations = parts.filter((p) => p.kind === 'math')
  assert.equal(equations.length, 4)
  assert.equal(equations.filter((p) => p.display).length, 2)
  for (const part of equations) assert.match(html(part), /class="katex/)
})

test('unfinished streamed formulas remain intact until closed', () => {
  for (const source of ['$$\\frac{1}{', '$x+', '\\[x^2', '正文 $$x+1']) {
    const parts = mathParts(source)
    assert.equal(parts.map((p) => p.raw).join(''), source)
    assert.equal(parts.filter((p) => p.kind === 'math').length, 0)
  }
  assert.match(html(mathParts('$$x+1$$')[0]), /katex-display/)
})

test('ordinary code and escaped dollars remain literal', () => {
  const source = '示例 `$$x$$`\n```python\ncost = "$5"\n```\n\\$10\n末尾$'
  const parts = mathParts(source)
  assert.equal(parts.filter((p) => p.kind === 'math').length, 0)
  assert.equal(parts.map((p) => p.raw).join(''), source)
})

test('AI latex fences render with and without extra math delimiters', () => {
  for (const body of [String.raw`\frac{1}{2}`, String.raw`$$\frac{1}{2}$$`]) {
    const parts = mathParts('```latex\n' + body + '\n```')
    assert.equal(parts.length, 1)
    assert.match(html(parts[0]), /katex-display/)
  }
})

test('unsupported formulas preserve their original source instead of disappearing', () => {
  const part = mathParts('$$\\unknowncommand{x}$$')[0]
  assert.equal(renderMathPart(part, katex).error, true)
  assert.equal(part.raw, '$$\\unknowncommand{x}$$')
})

test('rendering does not allow executable hrefs or raw HTML', () => {
  const part = mathParts(String.raw`$$\href{javascript:alert(1)}{x}$$`)[0]
  const rendered = renderMathPart(part, katex)
  assert.notMatch(rendered.html || '', /<a\s|href="javascript:/)
  const raw = '<img src=x onerror=alert(1)>'
  assert.equal(mathParts(raw)[0].kind, 'text')
  assert.equal(renderMathPart(mathParts(raw)[0], katex).html, undefined)
})

test('maintained definitions opt into complete scripts without changing raw source', () => {
  const source = '离散式 Σ_iΣ_j x_i y_j p_{ij}；连续式 ∬_{ℝ²}xy f_{X,Y}(x,y)dxdy。'
  assert.equal(mathParts(source).filter((p) => p.kind === 'math').length, 0)
  const parts = mathParts(source, { implicit: true }),
    equations = parts.filter((p) => p.kind === 'math')
  assert.equal(equations.length, 7)
  assert.equal(parts.map((p) => p.raw).join(''), source)
  for (const part of equations) assert.match(html(part), /class="katex/)
})

test('bare TeX commands keep complete groups and nested scripts', () => {
  const source = String.raw`公式 \frac{1}{\sqrt{x^2+1}}、\mathbb{R}^{n}、\alpha_i 与 x_{i_j}^{2}。`
  const parts = mathParts(source, { implicit: true })
  assert.equal(parts.filter((p) => p.kind === 'math').length, 4)
  assert.equal(parts.map((p) => p.raw).join(''), source)
  for (const part of parts.filter((p) => p.kind === 'math'))
    assert.match(html(part), /class="katex/)
})

test('implicit notation preserves prose, identifiers, code, damaged text and unfinished formulas', () => {
  const literal = String.raw`bank_id source_revision review_note a_total x_ij P,Q,Rin C^1 overlineOmega rge0 C:\Users\user`
  // C^1 is complete notation; broken Rin/overlineOmega/rge0 are never repaired.
  const parts = mathParts(literal, { implicit: true })
  assert.equal(parts.filter((p) => p.kind === 'math').length, 1)
  assert.equal(parts.find((p) => p.kind === 'math')?.text, 'C^1')
  assert.equal(parts.map((p) => p.raw).join(''), literal)
  for (const source of [
    '$$x_i+',
    '\\[x_i',
    String.raw`\frac{1}{`,
    `\`x_i\`\n\`\`\`python\nx_i=1\n\`\`\``,
  ]) {
    assert.equal(mathParts(source, { implicit: true }).filter((p) => p.kind === 'math').length, 0)
  }
})

test('implicit notation never renders an interior fragment of unfinished groups', () => {
  for (const source of [String.raw`\frac{x_i}{`, 'f_{x_i', 'p_{ij}}']) {
    const parts = mathParts(source, { implicit: true })
    assert.equal(parts.filter((p) => p.kind === 'math').length, 0)
    assert.equal(parts.map((p) => p.raw).join(''), source)
  }
})

test('unsupported bare commands and their arguments stay literal', () => {
  const source = String.raw`\unknowncommand{x_i}{y_j}，但 \alpha_i 可显示。`
  const parts = mathParts(source, { implicit: true })
  assert.equal(parts.filter((p) => p.kind === 'math').length, 1)
  assert.equal(parts.find((p) => p.kind === 'math')?.text, String.raw`\alpha_i`)
  assert.equal(parts.map((p) => p.raw).join(''), source)
})
