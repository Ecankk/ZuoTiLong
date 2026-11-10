import type { ReactNode } from 'react'
import { Link } from 'react-router'
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
