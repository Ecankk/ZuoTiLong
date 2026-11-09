export type Choice = { letter: string; text: string }
export type SplitChoices = { stem: string; choices: Choice[] }

const letters = ['A', 'B', 'C', 'D', 'E']

/** 行首的选项标记：A. / A． / A、 / A: / (A) / （A） */
const lineMark = /^[ \t\u3000]*[(（]?([A-E])[)）]?[ \t\u3000]*[.．、:：)）]?[ \t\u3000]*/
/** 同一行里的选项标记，前面必须是空白或行首，后面必须有点号或括号 */
const inlineMark = /(^|[\s\u3000])[(（]?([A-E])[ \t\u3000]*[.．、:：)）][ \t\u3000]*/g

/** 字母要从 A 开始依次出现，至少两个 */
function inOrder(found: string[]) {
  return found.length >= 2 && found.every((letter, index) => letter === letters[index])
}

/** 把公式（$…$、$$…$$、\(…\)、\[…\]）换成等长的占位，避免把公式里的“A.”当成选项 */
function maskMath(text: string) {
  return text.replace(/\$\$[\s\S]*?\$\$|\$[^$]*\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]/g, (m) =>
    '\u0000'.repeat(m.length),
  )
}

function byLines(text: string): SplitChoices | null {
  const lines = text.split('\n')
  const marks: { index: number; letter: string }[] = []
  lines.forEach((line, index) => {
    const match = /^[ \t\u3000]*[(（]?([A-E])[ \t\u3000]*(?:[.．、:：]|[)）])/.exec(line)
    if (match) marks.push({ index, letter: match[1] })
  })
  if (!inOrder(marks.map((m) => m.letter))) return null
  const choices = marks.map((mark, i) => {
    const end = marks[i + 1]?.index ?? lines.length
    const body = lines.slice(mark.index, end).join('\n').replace(lineMark, '').trim()
    return { letter: mark.letter, text: body }
  })
  if (choices.some((c) => !c.text)) return null
  return { stem: lines.slice(0, marks[0].index).join('\n').trim(), choices }
}

function inline(text: string): SplitChoices | null {
  const masked = maskMath(text)
  const marks: { start: number; body: number; letter: string }[] = []
  for (const match of masked.matchAll(inlineMark)) {
    const start = match.index + match[1].length
    marks.push({ start, body: match.index + match[0].length, letter: match[2] })
  }
  // 只取从某个 A 开始、依次排列的一串
  const first = marks.findIndex((m) => m.letter === 'A')
  if (first < 0) return null
  const run: typeof marks = []
  for (const mark of marks.slice(first)) {
    if (mark.letter === letters[run.length]) run.push(mark)
  }
  if (!inOrder(run.map((m) => m.letter))) return null
  const choices = run.map((mark, i) => ({
    letter: mark.letter,
    text: text.slice(mark.body, run[i + 1]?.start ?? text.length).trim(),
  }))
  if (choices.some((c) => !c.text)) return null
  return { stem: text.slice(0, run[0].start).trim(), choices }
}

/**
 * 把选择题题面拆成题干和 A–D 选项。认不出时返回 null，按原样显示整段文字。
 * 先按行找（数据里选项通常各占一行），再在同一段里找（公式内的字母不算）。
 */
export function splitChoices(text: string | null | undefined): SplitChoices | null {
  if (!text) return null
  const result = byLines(text) ?? inline(text)
  if (!result || !result.stem) return null
  return result
}

/** 选项都很短时排成两列，否则每个选项一行 */
export function choicesAreShort(choices: Choice[]) {
  return choices.every((c) => c.text.replace(/\\[a-zA-Z]+|[{}$\s]/g, '').length <= 18)
}
