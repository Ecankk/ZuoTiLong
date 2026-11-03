import { useState } from 'react'
import { usePreferences, useSavePreferences } from '../../api/queries'
import type { Preferences } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
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
      {save.error && <p className={styles.error}>{save.error.message}</p>}
    </Card>
  )
}

function ConventionForm({ preferences }: { preferences: Preferences }) {
  const [text, setText] = useState(preferences.paper_marking_convention)
  const save = useSavePreferences()
  return (
    <>
      <textarea
        className={styles.textarea}
        maxLength={1000}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <div className={styles.row}>
        <Button
          disabled={save.isPending || text.trim() === preferences.paper_marking_convention}
          onClick={() => save.mutate({ paper_marking_convention: text.trim() })}
        >
          保存笔迹约定
        </Button>
        {save.isSuccess && <span className={styles.saved}>已保存，之后的分析会按这个约定</span>}
      </div>
      {save.error && <p className={styles.error}>{save.error.message}</p>}
    </>
  )
}

/** 笔迹约定（preferences.paper_marking_convention），分析试卷时交给做题龙参考。 */
export function ConventionCard() {
  const { data } = usePreferences()
  return (
    <Card padded className={styles.section} aria-label="笔迹约定">
      <h2>笔迹约定</h2>
      <p>告诉做题龙你的试卷上哪些是考试作答、哪些是事后批改。默认是黑笔作答、红笔批改。</p>
      {data && <ConventionForm key={data.paper_marking_convention} preferences={data} />}
    </Card>
  )
}
