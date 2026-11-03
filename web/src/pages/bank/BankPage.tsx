import { X } from 'lucide-react'
import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router'
import type { BankFilter } from '../../api/endpoints'
import { useBank, useBankTopics, useTopic } from '../../api/queries'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip } from '../../components/ui/Chip'
import { PageHeader } from '../../components/ui/PageHeader'
import { Segmented } from '../../components/ui/Segmented'
import { BankQuestionCard, BankQuestionDialog, type BankTopic } from './BankQuestion'
import styles from './BankPage.module.css'

const pageSize = 24
const thisYear = 2026
const years = Array.from({ length: thisYear - 1987 + 1 }, (_, i) => String(thisYear - i))

/**
 * 题库浏览：按类别、年份、考点筛选，地址栏保存筛选、页码和打开的题（?open=题目编号），
 * 方便从考点页直接跳到某道题。
 */
export function BankPage() {
  const [params, setParams] = useSearchParams()
  const filter: BankFilter = {
    mathType: params.get('math_type') ?? '',
    year: params.get('year') ?? '',
    topic: params.get('topic') ?? '',
  }
  const page = Math.max(1, Number(params.get('page')) || 1)
  const openId = params.get('open')
  const { data, isPending, isError, error, isPlaceholderData } = useBank(
    filter,
    (page - 1) * pageSize,
    pageSize,
  )
  const { data: topic } = useTopic(filter.topic || undefined)
  // 接口按题目编号排序；本页内按年份、题号排列更好找
  const items = useMemo(
    () =>
      [...(data?.items ?? [])].sort(
        (a, b) =>
          Number(b.year) - Number(a.year) || a.math_type - b.math_type || a.number - b.number,
      ),
    [data],
  )
  const { data: topicData } = useBankTopics(items.map((item) => item.id))
  const topicsOf = (id: string): BankTopic[] =>
    topicData?.items.find((item) => item.bank_id === id)?.topics ?? []

  const update = (change: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(change)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    if (!('page' in change)) next.delete('page')
    setParams(next)
  }
  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1
  const opened = items.find((item) => item.id === openId)

  return (
    <>
      <PageHeader title="题库" subtitle="历年真题，可按类别、年份和考点筛选。" />
      <Card className={styles.filters} aria-label="筛选">
        <Segmented<string>
          label="类别"
          items={[
            { value: '', label: '全部' },
            { value: '1', label: '数学一' },
            { value: '2', label: '数学二' },
            { value: '3', label: '数学三' },
          ]}
          value={filter.mathType}
          onChange={(value) => update({ math_type: value })}
        />
        <label className={styles.yearField}>
          年份
          <select value={filter.year} onChange={(event) => update({ year: event.target.value })}>
            <option value="">全部年份</option>
            {years.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        </label>
        {filter.topic && (
          <span className={styles.topicFilter}>
            考点：
            <Link to={`/topics/${encodeURIComponent(filter.topic)}`}>
              <Chip tone="primary">{topic?.topic.name ?? '加载中…'}</Chip>
            </Link>
            <button type="button" aria-label="清除考点筛选" onClick={() => update({ topic: '' })}>
              <X size={14} aria-hidden />
            </button>
          </span>
        )}
        {data && <span className={styles.count}>共 {data.total} 题</span>}
      </Card>

      {isError && (
        <Card padded className={styles.notice}>
          {error.message}
        </Card>
      )}
      {isPending && (
        <Card padded className={styles.notice}>
          正在读取…
        </Card>
      )}
      {data && data.total === 0 && (
        <Card padded className={styles.notice}>
          没有符合条件的题目，换个类别或年份试试。
        </Card>
      )}
      <div className={styles.grid} style={{ opacity: isPlaceholderData ? 0.6 : 1 }}>
        {items.map((card) => (
          <BankQuestionCard
            key={card.id}
            card={card}
            topics={topicsOf(card.id)}
            onOpen={() => update({ open: card.id, page: String(page) })}
          />
        ))}
      </div>
      {data && data.total > pageSize && (
        <nav className={styles.pager} aria-label="分页">
          <Button size="sm" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>
            上一页
          </Button>
          <span>
            第 {page} / {totalPages} 页
          </span>
          <Button
            size="sm"
            disabled={data.next_offset === null}
            onClick={() => update({ page: String(page + 1) })}
          >
            下一页
          </Button>
        </nav>
      )}
      {opened && (
        <BankQuestionDialog
          card={opened}
          topics={topicsOf(opened.id)}
          onClose={() => update({ open: '', page: String(page) })}
        />
      )}
    </>
  )
}
