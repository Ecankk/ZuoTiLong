export type MathPart = { kind: 'text' | 'math' | 'code'; text: string; raw: string; display: boolean }
export type MathEngine = { renderToString: (text: string, options: Record<string, unknown>) => string }

/** Recognize complete math delimiters; preserve incomplete streaming text verbatim. */
export function mathParts(source: string): MathPart[] {
  const result: MathPart[] = []
  let plain = '', cursor = 0
  const escaped = (at: number) => {
    let count = 0
    while (at > 0 && source[--at] === '\\') count++
    return count % 2 === 1
  }
  const flush = () => { if (plain) result.push({kind:'text', text:plain, raw:plain, display:false}); plain = '' }
  while (cursor < source.length) {
    const fence = /^(\`\`\`|~~~)([\w-]*)[^\n]*\n/.exec(source.slice(cursor))
    if (fence && (cursor === 0 || source[cursor - 1] === '\n')) {
      const end = source.indexOf(fence[1], cursor + fence[0].length)
      if (end < 0) { plain += source.slice(cursor); break }
      flush()
      const raw = source.slice(cursor, end + fence[1].length)
      const body = source.slice(cursor + fence[0].length, end).trim()
      if (['math','latex','tex'].includes(fence[2].toLowerCase())) {
        const inner = mathParts(body)
        if (inner.some(p => p.kind === 'math')) result.push(...inner)
        else result.push({kind:'math', text:body, raw, display:true})
      } else result.push({kind:'code', text:raw, raw, display:false})
      cursor = end + fence[1].length
      continue
    }
    if (source[cursor] === '`' && !escaped(cursor)) {
      const ticks = /^`+/.exec(source.slice(cursor))![0]
      const end = source.indexOf(ticks, cursor + ticks.length)
      if (end >= 0) {
        flush()
        const raw = source.slice(cursor, end + ticks.length)
        result.push({kind:'code', text:raw, raw, display:false})
        cursor = end + ticks.length
        continue
      }
    }
    const delimiter = escaped(cursor) ? undefined : [
      {open:'$$', close:'$$', display:true}, {open:'\\[', close:'\\]', display:true},
      {open:'\\(', close:'\\)', display:false}, {open:'$', close:'$', display:false},
    ].find(d => source.startsWith(d.open, cursor))
    if (delimiter) {
      let end = cursor + delimiter.open.length
      while (end < source.length) {
        if (!delimiter.display && source[end] === '\n') break
        if (source.startsWith(delimiter.close, end) && !escaped(end) &&
          !(delimiter.close === '$' && (source[end+1] === '$' || source[end-1] === '$'))) break
        end++
      }
      if (end < source.length && source.startsWith(delimiter.close, end)) {
        flush()
        result.push({kind:'math', text:source.slice(cursor+delimiter.open.length,end), raw:source.slice(cursor,end+delimiter.close.length), display:delimiter.display})
        cursor = end + delimiter.close.length
        continue
      }
      // Do not consume half of an unfinished $$ opening as a single $.
      plain += delimiter.open
      cursor += delimiter.open.length
      continue
    }
    plain += source[cursor++]
  }
  flush()
  return result
}

export function renderMathPart(part: MathPart, engine?: MathEngine): {html?: string; error?: boolean} {
  if (part.kind !== 'math' || !engine) return {}
  try {
    return {html: engine.renderToString(part.text, {throwOnError:true, trust:false, displayMode:part.display, strict:'ignore'})}
  } catch { return {error:true} }
}
