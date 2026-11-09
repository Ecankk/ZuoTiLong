/**
 * 考点名里常有 ASCII 数学写法（“e^x 在 0 点的泰勒展开”“极大似然估计的 argmax 定义”）。
 * 把这些片段包成 \(…\) 交给 MathText 排版；已经带公式定界符的名称原样返回。
 * 只处理含 ^ 的连续 ASCII 片段和 argmax/argmin，其余文字不动。
 */
export function topicNameMath(name: string): string {
  if (/\\\(|\\\[|\$/.test(name)) return name
  return name
    .replace(/\barg\s?(max|min)\b/g, '\\(\\arg\\$1\\)')
    .replace(/[A-Za-z0-9α-ωΑ-Ω()+\-*/'=.,]*\^[A-Za-z0-9α-ωΑ-Ω()+\-*/'=.,^]+/g, (chunk) => {
      // 结尾的标点不算公式
      const tail = /[.,]+$/.exec(chunk)?.[0] ?? ''
      const body = chunk.slice(0, chunk.length - tail.length)
      // 括号要成对，否则不像完整记号，保持原文
      const open = (body.match(/\(/g) ?? []).length
      if (open !== (body.match(/\)/g) ?? []).length) return chunk
      // ^ 后面多于一个字符时加花括号：x^10 → x^{10}；^(...) → ^{...}
      const tex = body
        .replace(/\^\(([^()]*)\)/g, '^{$1}')
        .replace(/\^([A-Za-z0-9α-ωΑ-Ω]{2,})/g, '^{$1}')
      return `\\(${tex}\\)${tail}`
    })
}
