export type MathPart = {
  kind: 'text' | 'math' | 'code'
  text: string
  raw: string
  display: boolean
}
export type MathEngine = {
  renderToString: (text: string, options: Record<string, unknown>) => string
}

/** Recognize complete math delimiters; preserve incomplete streaming text verbatim. */
export function mathParts(
  source: string | null | undefined,
  options: { implicit?: boolean } = {},
): MathPart[] {
  if (typeof source !== 'string') return []
  const result: MathPart[] = []
  let plain = '',
    cursor = 0
  const escaped = (at: number) => {
    let count = 0
    while (at > 0 && source[--at] === '\\') count++
    return count % 2 === 1
  }
  const flush = () => {
    if (plain) result.push({ kind: 'text', text: plain, raw: plain, display: false })
    plain = ''
  }
  while (cursor < source.length) {
    const fence = /^(```|~~~)([\w-]*)[^\n]*\n/.exec(source.slice(cursor))
    if (fence && (cursor === 0 || source[cursor - 1] === '\n')) {
      const end = source.indexOf(fence[1], cursor + fence[0].length)
      if (end < 0) {
        plain += source.slice(cursor)
        break
      }
      flush()
      const raw = source.slice(cursor, end + fence[1].length)
      const body = source.slice(cursor + fence[0].length, end).trim()
      if (['math', 'latex', 'tex'].includes(fence[2].toLowerCase())) {
        const inner = mathParts(body)
        if (inner.some((p) => p.kind === 'math')) result.push(...inner)
        else result.push({ kind: 'math', text: body, raw, display: true })
      } else result.push({ kind: 'code', text: raw, raw, display: false })
      cursor = end + fence[1].length
      continue
    }
    if (source[cursor] === '`' && !escaped(cursor)) {
      const ticks = /^`+/.exec(source.slice(cursor))![0]
      const end = source.indexOf(ticks, cursor + ticks.length)
      if (end >= 0) {
        flush()
        const raw = source.slice(cursor, end + ticks.length)
        result.push({ kind: 'code', text: raw, raw, display: false })
        cursor = end + ticks.length
        continue
      }
    }
    const delimiter = escaped(cursor)
      ? undefined
      : [
          { open: '$$', close: '$$', display: true },
          { open: '\\[', close: '\\]', display: true },
          { open: '\\(', close: '\\)', display: false },
          { open: '$', close: '$', display: false },
        ].find((d) => source.startsWith(d.open, cursor))
    if (delimiter) {
      let end = cursor + delimiter.open.length
      while (end < source.length) {
        if (!delimiter.display && source[end] === '\n') break
        if (
          source.startsWith(delimiter.close, end) &&
          !escaped(end) &&
          !(delimiter.close === '$' && (source[end + 1] === '$' || source[end - 1] === '$'))
        )
          break
        end++
      }
      if (end < source.length && source.startsWith(delimiter.close, end)) {
        flush()
        result.push({
          kind: 'math',
          text: source.slice(cursor + delimiter.open.length, end),
          raw: source.slice(cursor, end + delimiter.close.length),
          display: delimiter.display,
        })
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
  return options.implicit
    ? result.flatMap((part) => (part.kind === 'text' ? implicitParts(part.text) : [part]))
    : result
}

/** Opt-in display for complete, unmistakable notation in maintained definitions.
 * Keep raw source intact: no inferred operators, repaired commands or data edits.
 */
function implicitParts(source: string): MathPart[] {
  const literal = (): MathPart[] => [{ kind: 'text', text: source, raw: source, display: false }]
  // Leave an unfinished explicit formula alone, even if its prefix is parseable.
  if (['$', '\\(', '\\)', '\\[', '\\]'].some((mark) => source.includes(mark))) {
    return literal()
  }
  let balance = 0
  for (let i = 0; i < source.length; i++) {
    if (source[i] === '\\' && ['{', '}', '\\'].includes(source[i + 1])) {
      i++
      continue
    }
    if (source[i] === '{') balance++
    if (source[i] === '}' && --balance < 0) return literal()
  }
  if (balance) return literal()
  const parts: MathPart[] = []
  const braced = (start: number): number | undefined => {
    if (source[start] !== '{') return undefined
    let depth = 0
    for (let pos = start; pos < Math.min(source.length, start + 2048); pos++) {
      if (source[pos] === '\n') return undefined
      if (source[pos] === '\\' && ['{', '}', '\\'].includes(source[pos + 1])) {
        pos++
        continue
      }
      if (source[pos] === '{') depth++
      if (source[pos] === '}' && --depth === 0) return pos + 1
    }
    return undefined
  }
  const scripted = (start: number): number | undefined => {
    let end = start
    const seen = new Set<string>()
    while (source[end] === '_' || source[end] === '^') {
      if (seen.has(source[end])) return undefined
      seen.add(source[end++])
      if (source[end] === '{') {
        const next = braced(end)
        if (next === undefined) return undefined
        end = next
      } else {
        const token = /^(?:\\[A-Za-z]+|[\p{L}\p{N}])/u.exec(source.slice(end))
        if (!token) return undefined
        end += token[0].length
        if (/[A-Za-z0-9]/.test(source[end] || '')) return undefined
      }
    }
    return end
  }
  const commands = new Set(
    'alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega sum prod int iint iiint lim limsup liminf infty partial nabla in notin ge geq le leq ne neq to rightarrow cdot times forall exists subset subseteq cup cap'.split(
      ' ',
    ),
  )
  const oneGroup = new Set([
    'mathbb',
    'mathbf',
    'mathcal',
    'mathrm',
    'overline',
    'underline',
    'hat',
    'bar',
    'vec',
  ])
  const match = (at: number): number | undefined => {
    const rest = source.slice(at)
    let end: number | undefined
    if (source[at] === '\\') {
      let backslashes = 0
      for (let i = at - 1; i >= 0 && source[i] === '\\'; i--) backslashes++
      if (backslashes % 2) return undefined
      const command = /^\\([A-Za-z]+)/.exec(rest)
      if (!command) return undefined
      end = at + command[0].length
      if (['frac', 'dfrac', 'tfrac'].includes(command[1])) {
        end = braced(end)
        if (end !== undefined) end = braced(end)
      } else if (oneGroup.has(command[1])) end = braced(end)
      else if (command[1] === 'sqrt') {
        if (source[end] === '[') {
          const close = source.indexOf(']', end + 1)
          if (close < 0 || source.slice(end, close).includes('\n')) return undefined
          end = close + 1
        }
        end = braced(end)
      } else if (!commands.has(command[1])) return undefined
      return end === undefined ? undefined : scripted(end)
    }
    // Multi-letter identifiers such as bank_id and local paths are prose.
    const operator = /^[Σ∑∫∬∭]/.test(rest)
    if (!operator && /[A-Za-z0-9_\\]/.test(source[at - 1] || '')) return undefined
    const base = /^(?:[A-Za-zΑ-Ωα-ωℝℂℤℕℚΣ∑∫∬∭]|\d+(?:\.\d+)?)/.exec(rest)
    if (!base) return undefined
    end = at + base[0].length
    if (source[end] !== '_' && source[end] !== '^') return undefined
    return scripted(end)
  }
  let cursor = 0,
    plainStart = 0
  while (cursor < source.length) {
    // An unknown command with arguments stays opaque; do not typeset its body
    // independently and make an unsupported expression appear partly valid.
    if (source[cursor] === '\\') {
      const command = /^\\([A-Za-z]+)/.exec(source.slice(cursor))
      if (
        command &&
        !commands.has(command[1]) &&
        !oneGroup.has(command[1]) &&
        !['frac', 'dfrac', 'tfrac', 'sqrt'].includes(command[1])
      ) {
        let end = cursor + command[0].length
        while (source[end] === '{') end = braced(end) ?? end + 1
        cursor = end
        continue
      }
    }
    const end = match(cursor)
    if (end === undefined || end <= cursor) {
      cursor++
      continue
    }
    if (cursor > plainStart) {
      const raw = source.slice(plainStart, cursor)
      parts.push({ kind: 'text', text: raw, raw, display: false })
    }
    const raw = source.slice(cursor, end)
    parts.push({ kind: 'math', text: raw, raw, display: false })
    cursor = end
    plainStart = end
  }
  if (plainStart < source.length) {
    const raw = source.slice(plainStart)
    parts.push({ kind: 'text', text: raw, raw, display: false })
  }
  return parts
}

export function renderMathPart(
  part: MathPart,
  engine?: MathEngine,
): { html?: string; error?: boolean } {
  if (part.kind !== 'math' || !engine) return {}
  try {
    return {
      html: engine.renderToString(part.text, {
        throwOnError: true,
        trust: false,
        displayMode: part.display,
        strict: 'ignore',
      }),
    }
  } catch {
    return { error: true }
  }
}
