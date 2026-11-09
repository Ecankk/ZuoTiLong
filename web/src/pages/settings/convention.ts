/**
 * 笔迹约定在后端是一段给 AI 看的文字（preferences.paper_marking_convention）。
 * 设置页用两个选项（作答笔色、批改笔色）加一句补充说明来编辑它，保存时拼回文字：
 * 第 1、2 行换掉默认文字里的颜色，其余默认规则原样保留，补充说明写在最后。
 * 文字被手动改过、对不上这个格式时，选项区只显示默认值，原文在高级设置里改。
 */

export type ExamPen = '黑' | '蓝'
export type MarkPen = '红' | '绿'
export type Convention = { exam: ExamPen; mark: MarkPen; note: string }

export const examPens: ExamPen[] = ['黑', '蓝']
export const markPens: MarkPen[] = ['红', '绿']

/** 后端没返回 default_agent_prompt 时用的默认约定（和 app/bank/access.py 一致） */
export const fallbackDefault = [
  '黑色手写笔迹为考试时的作答，包括涂改和自查修正；印刷题干不算作答。',
  '红色手写笔迹为事后批改，不作为独立作答证据。',
  '已确认空白纳入未完成/错题补强，保留未作答事实；没思路、时间不足等仅为可能背景，不逐题追问，也不据此断定具体能力。缺页或漏扫另记材料不足。',
  '某份试卷有明确例外时，以用户对该卷的说明为准。',
].join('\n')

const notePrefix = '补充说明：'

export function buildConvention(base: string, { exam, mark, note }: Convention) {
  const lines = base.split('\n')
  lines[0] = lines[0].replace(/^[黑蓝]色/, `${exam}色`)
  if (lines.length > 1) lines[1] = lines[1].replace(/^[红绿]色/, `${mark}色`)
  const extra = note.trim().replace(/\s*\n\s*/g, ' ')
  return [...lines, ...(extra ? [notePrefix + extra] : [])].join('\n')
}

/** 认出当前文字对应的选项；认不出（被手动改过）时返回 null */
export function parseConvention(text: string, base: string): Convention | null {
  for (const exam of examPens)
    for (const mark of markPens) {
      const plain = buildConvention(base, { exam, mark, note: '' })
      if (text === plain) return { exam, mark, note: '' }
      if (text.startsWith(`${plain}\n${notePrefix}`))
        return { exam, mark, note: text.slice(plain.length + 1 + notePrefix.length) }
    }
  return null
}
