import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { usePreferences, useProfile } from '../api/queries'
import { Card } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import styles from './Placeholder.module.css'

/** 尚未实现的页面：保留标题和将要展示的内容说明。 */
export function PlaceholderPage({
  title,
  intro,
  items,
  header,
}: {
  title: string
  intro: string
  items: string[]
  header?: ReactNode
}) {
  return (
    <>
      {header ?? <PageHeader title={title} />}
      <Card padded className={styles.card}>
        <p>{intro}</p>
        <ul>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </Card>
    </>
  )
}

/** 自由练习汇总（GET /api/profile 的 free_practice）；设置里关闭计入时后端不再统计 */
function FreePracticeSummary() {
  const { data } = useProfile()
  const { data: preferences } = usePreferences()
  const free = data?.free_practice
  if (!free) return null
  return (
    <Card padded className={styles.card} aria-label="自由练习">
      <h2 className={styles.title}>自由练习</h2>
      {preferences?.include_free_practice === false ? (
        <p className={styles.muted}>
          你在设置里选择了画像不计入自由练习，做过的记录仍然保留在每道题的历史里。
        </p>
      ) : free.total === 0 ? (
        <p className={styles.muted}>还没有自由练习。在题库或考点页打开一道题，点“做这道题”即可。</p>
      ) : (
        <>
          <dl className={styles.stats}>
            <div>
              <dt>做过</dt>
              <dd>{free.total} 次</dd>
            </div>
            <div>
              <dt>独立做对</dt>
              <dd>{free.independent_correct}</dd>
            </div>
            <div>
              <dt>看过答案后做对</dt>
              <dd>{free.assisted_correct}</dd>
            </div>
            <div>
              <dt>做错</dt>
              <dd>{free.wrong}</dd>
            </div>
            {free.pending > 0 && (
              <div>
                <dt>待批改</dt>
                <dd>{free.pending}</dd>
              </div>
            )}
          </dl>
          <p className={styles.muted}>
            自由练习和原卷、对口练习分开统计；看过答案后做对的不算独立完成。
          </p>
        </>
      )}
    </Card>
  )
}

export const ProfilePage = () => (
  <>
    <PageHeader title="画像" />
    <FreePracticeSummary />
    <Card padded className={styles.card}>
      <p>画像还在开发中，后续版本提供。</p>
      <p className={styles.muted}>
        现在可以在“考点”里查看每个考点的做题情况，在“试卷”里查看每份试卷的正误分布。
      </p>
    </Card>
  </>
)

export const NotFoundPage = () => (
  <>
    <PageHeader title="没有找到这个页面" />
    <Card padded className={styles.card}>
      <p>这个地址没有对应的页面，可能链接已经过期。可以回到：</p>
      <ul>
        <li>
          <Link to="/">首页</Link>
        </li>
        <li>
          <Link to="/papers">试卷</Link>
        </li>
        <li>
          <Link to="/practice">练习</Link>
        </li>
      </ul>
    </Card>
  </>
)
