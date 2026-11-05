const letters = ['A', 'B', 'C', 'D'] as const

/**
 * 从题面文字里找出已有的选项字母（A. / A． / A、 / (A) / （A）等写法）。
 * 找不到两个以上时按 A–D 四个给出：选择题的参考答案就是单个字母。
 */
export function choiceLetters(text: string | undefined): string[] {
  const found = new Set<string>()
  const pattern = /(?:^|[\s$（(])[(（]?([A-D])\s*(?:[.．、:：)）]|\[.,;])/g
  for (const match of (text ?? '').matchAll(pattern)) found.add(match[1])
  const result = letters.filter((letter) => found.has(letter))
  return result.length >= 2 ? result : [...letters]
}
