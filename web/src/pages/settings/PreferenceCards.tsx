import { useState } from 'react'
import { usePreferences, useSavePreferences } from '../../api/queries'
import type { Preferences } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Segmented } from '../../components/ui/Segmented'
import { friendlyError } from '../../lib/errors'
import {
  buildConvention,
  examPens,
  fallbackDefault,
  markPens,
  parseConvention,
  type Convention,
  type ExamPen,
  type MarkPen,
} from './convention'
import styles from './SettingsPage.module.css'

/** 同类别真题默认遮挡（preferences.mask_same_type） */
export function MaskCard() {
  const { data } = usePreferences()
  const save = useSavePreferences()
  if (!data) return null
  return (
    <Card padded className={styles.section} aria-label="真题遮挡">
      <h2>同类别真题遮挡</h2>
      <p>练习里出现和你备考类别相同的真题时，默认先遮住题目，确认后再看，方便以后整卷自测。</p>
      <label className={styles.switchRow}>
        <input
          type="checkbox"
          checked={data.mask_same_type}
          disabled={save.isPending}
          onChange={(event) => save.mutate({ mask_same_type: event.target.checked })}
        />
        遮挡同类别真题
      </label>
      {save.error && <p className={styles.error}>{friendlyError(save.error)}</p>}
    </Card>
  )
}

/** 画像计入自由练习（preferences.include_free_practice，默认计入） */
export function FreePracticeCard() {
  const { data } = usePreferences()
  const save = useSavePreferences()
  if (!data) return null
  return (
    <Card padded className={styles.section} aria-label="自由练习">
      <h2>自由练习</h2>
      <p>
        在题库里单独做的题会记成“自由练习”，和原卷、对口练习分开统计。关闭后画像和考点表现不再计入，做过的记录仍然保留。
      </p>
      <label className={styles.switchRow}>
        <input
          type="checkbox"
          checked={data.include_free_practice !== false}
          disabled={save.isPending}
          onChange={(event) => save.mutate({ include_free_practice: event.target.checked })}
        />
        画像计入自由练习
      </label>
      {save.error && <p className={styles.error}>{friendlyError(save.error)}</p>}
    </Card>
  )
}

/** 后端在偏好里附带的默认约定原文（类型里没有，读不到时用前端的备份） */
const defaultConvention = (preferences: Preferences) =>
  (preferences as Preferences & { default_agent_prompt?: string }).default_agent_prompt ||
  fallbackDefault

const penItems = <T extends ExamPen | MarkPen>(pens: T[]) =>
  pens.map((pen) => ({ value: pen, label: `${pen}笔` }))

function ConventionForm({ preferences }: { preferences: Preferences }) {
  const base = defaultConvention(preferences)
  const parsed = parseConvention(preferences.paper_marking_convention, base)
  const [value, setValue] = useState<Convention>(parsed ?? { exam: '黑', mark: '红', note: '' })
  const save = useSavePreferences()
  const text = buildConvention(base, value)
  const changed = text !== preferences.paper_marking_convention
  const update = (change: Partial<Convention>) => {
    save.reset()
    setValue((current) => ({ ...current, ...change }))
  }
  return (
    <>
      <div className={styles.penRows}>
        <div className={styles.penRow}>
          <span>考试时作答用</span>
          <Segmented<ExamPen>
            label="考试时作答用的笔"
            items={penItems(examPens)}
            value={value.exam}
            onChange={(exam) => update({ exam })}
          />
        </div>
        <div className={styles.penRow}>
          <span>考后批改用</span>
          <Segmented<MarkPen>
            label="考后批改用的笔"
            items={penItems(markPens)}
            value={value.mark}
            onChange={(mark) => update({ mark })}
          />
        </div>
      </div>
      <label className={styles.noteField}>
        <span>补充说明（可不填）</span>
        <input
          type="text"
          maxLength={200}
          placeholder="例如：草稿区的铅笔字不算作答"
          value={value.note}
          onChange={(event) => update({ note: event.target.value })}
        />
      </label>
      {!parsed && (
        <p className={styles.warnBox}>
          你在“高级设置”里改过约定原文。在这里保存会换成上面的选项，原文的改动不再保留。
        </p>
      )}
      <div className={styles.row}>
        <Button
          disabled={save.isPending || !changed}
          onClick={() => save.mutate({ paper_marking_convention: text })}
        >
          保存笔迹约定
        </Button>
        {save.isSuccess && <span className={styles.saved}>已保存，之后的分析会按这个约定</span>}
      </div>
      {save.error && <p className={styles.error}>{friendlyError(save.error)}</p>}
    </>
  )
}

/** 笔迹约定：考试作答和考后批改各用什么颜色的笔，分析试卷时交给做题龙参考。 */
export function ConventionCard() {
  const { data } = usePreferences()
  return (
    <Card padded className={styles.section} aria-label="笔迹约定">
      <h2>笔迹约定</h2>
      <p>告诉做题龙试卷上哪些是考试时写的、哪些是考后批改的，它才能分清你的作答和订正。</p>
      {data && <ConventionForm key={data.paper_marking_convention} preferences={data} />}
    </Card>
  )
}

function ConventionRawForm({ preferences }: { preferences: Preferences }) {
  const [text, setText] = useState(preferences.paper_marking_convention)
  const save = useSavePreferences()
  return (
    <>
      <textarea
        className={styles.textarea}
        aria-label="笔迹约定原文"
        maxLength={1000}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <div className={styles.row}>
        <Button
          size="sm"
          disabled={save.isPending || text.trim() === preferences.paper_marking_convention}
          onClick={() => save.mutate({ paper_marking_convention: text.trim() })}
        >
          保存原文
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={save.isPending}
          onClick={() => setText(defaultConvention(preferences))}
        >
          填回默认原文
        </Button>
        {save.isSuccess && <span className={styles.saved}>已保存</span>}
      </div>
      {save.error && <p className={styles.error}>{friendlyError(save.error)}</p>}
    </>
  )
}

/** 高级设置里的笔迹约定原文：做题龙分析试卷时实际读到的文字。 */
export function ConventionRaw() {
  const { data } = usePreferences()
  return (
    <section className={styles.subsection} aria-label="笔迹约定原文">
      <h3>笔迹约定原文</h3>
      <p>上面“笔迹约定”的选项会拼成这段文字交给做题龙。有特殊情况时可以直接改，一般不需要动。</p>
      {data && <ConventionRawForm key={data.paper_marking_convention} preferences={data} />}
    </section>
  )
}
