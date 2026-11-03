import katex from 'katex'
import { mathParts, renderMathPart } from '../../lib/math'

/**
 * 渲染带 $…$、$$…$$、\(…\)、\[…\] 公式的文字。无法排版的公式保留原文，不吞掉内容。
 * implicit 用于维护过的考点定义，识别不带定界符的完整记号。
 */
export function MathText({ text, implicit = false }: { text?: string | null; implicit?: boolean }) {
  return (
    <>
      {mathParts(text, { implicit }).map((part, index) => {
        const rendered = renderMathPart(part, katex)
        if (rendered.html)
          return <span key={index} dangerouslySetInnerHTML={{ __html: rendered.html }} />
        if (rendered.error)
          return (
            <code key={index} title="公式暂时无法排版，保留原文">
              {part.raw}
            </code>
          )
        return <span key={index}>{part.raw}</span>
      })}
    </>
  )
}
