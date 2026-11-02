import type { ReactNode } from 'react'
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

export const TopicsPage = () => (
  <PlaceholderPage
    title="考点"
    intro="这里将按章节展示考点树，选中考点后查看："
    items={['定义与适用条件', '关联题：已完成的题 / 全部题库', '我在这个考点的做题情况']}
  />
)

export const ProfilePage = () => (
  <PlaceholderPage
    title="画像"
    intro="这里将用图表展示你的整体情况："
    items={['成绩趋势', '各科目与章节的正确率', '薄弱考点排行', '练习完成情况与独立正确率']}
  />
)

export const BankPage = () => (
  <PlaceholderPage
    title="题库"
    intro="这里可以浏览全部真题，并按以下条件筛选："
    items={['数学一 / 数学二 / 数学三', '年份', '考点']}
  />
)

export const NotFoundPage = () => (
  <PlaceholderPage
    title="没有找到这个页面"
    intro="可以从左侧导航回到："
    items={['首页', '试卷', '练习']}
  />
)
