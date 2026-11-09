import { MathText } from '../../components/math/MathText'
import { cx } from '../../lib/cx'
import styles from './QuestionText.module.css'
import { choicesAreShort, splitChoices } from './splitChoices'

/**
 * 题面文字：选择题把 A–D 选项拆出来排成网格（短选项两列，长选项每个一行）；
 * 认不出选项时按原样显示，保留换行。
 */
export function QuestionText({ text }: { text: string }) {
  const split = splitChoices(text)
  if (!split)
    return (
      <div className={cx('read', styles.text)}>
        <MathText text={text} />
      </div>
    )
  return (
    <div className="read">
      <div className={styles.text}>
        <MathText text={split.stem} />
      </div>
      <ol
        className={cx(styles.choices, choicesAreShort(split.choices) && styles.short)}
        aria-label="选项"
      >
        {split.choices.map((choice) => (
          <li key={choice.letter}>
            <span className={styles.letter}>{choice.letter}</span>
            <span className={styles.choiceText}>
              <MathText text={choice.text} />
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}
