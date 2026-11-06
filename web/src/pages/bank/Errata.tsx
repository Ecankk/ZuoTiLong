import type { Erratum } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Fold } from '../../components/ui/Fold'
import styles from './BankPage.module.css'

/** 依据里可能直接写出答案的勘误 */
const revealsAnswer = (role: string) => role === 'answer' || role === 'analysis'

function roleName(role: string) {
  if (role === 'stem') return '题干'
  if (role === 'answer') return '答案'
  if (role === 'analysis') return '解析'
  const option = role.match(/^option:(.+)$/)
  return option ? `选项 ${option[1]}` : '题目'
}

/**
 * “本题已按勘误修正”，可展开看理由和依据。
 * 答案、解析类的勘误只在答案或解析已经可见时才显示内容，不能借这里绕过查看确认。
 */
export function ErrataNote({
  errata,
  answerVisible,
}: {
  errata: Erratum[] | undefined
  answerVisible: boolean
}) {
  if (!errata?.length) return null
  return (
    <div className={styles.errata}>
      <Fold title="本题已按勘误修正" hint="展开查看理由和依据">
        <ul>
          {errata.map((item, index) =>
            revealsAnswer(item.role) && !answerVisible ? (
              <li key={index} className={styles.errataHidden}>
                有一处{roleName(item.role)}
                勘误，内容可能涉及答案，查看答案或解析后可以看到理由和依据。
              </li>
            ) : (
              <li key={index}>
                <strong>{roleName(item.role)}：</strong>
                <MathText text={item.reason} />
                {item.evidence && (
                  <p className={styles.errataEvidence}>
                    依据：
                    <MathText text={item.evidence} />
                  </p>
                )}
              </li>
            ),
          )}
        </ul>
      </Fold>
    </div>
  )
}
