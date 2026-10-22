import { mathParts, renderMathPart, type MathEngine } from './math'

declare global { interface Window { katex?: MathEngine } }

export function MathText({ text }: { text: string }) {
  const engine = typeof window === 'undefined' ? undefined : window.katex
  return <span className="math-text">{mathParts(text).map((part, index) => {
    const rendered = renderMathPart(part, engine)
    if (rendered.html) return <span key={index} dangerouslySetInnerHTML={{__html:rendered.html}}/>
    if (rendered.error) return <code key={index} className="math-error" title="公式暂时无法排版，保留原文">{part.raw}</code>
    return <span key={index}>{part.raw}</span>
  })}</span>
}
