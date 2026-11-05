import { X } from 'lucide-react'
import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router'
import type { BankFilter } from '../../api/endpoints'
import { useBank, useBankCollections, useBankTopics, useTopic } from '../../api/queries'
import type { BankCard } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip } from '../../components/ui/Chip'
import { PageHeader } from '../../components/ui/PageHeader'
import { Segmented } from '../../components/ui/Segmented'
import { BankQuestionCard, BankQuestionDialog, bookSection, type BankTopic } from './BankQuestion'
import styles from './BankPage.module.css'
import { TopicSearch } from './TopicSearch'

const pageSize = 24
const typeLabel: Record<string, string> = { '1': '数一', '2': '数二', '3': '数三' }
const thisYear = 2026
const years = Array.from({ length: thisYear - 1987 + 1 }, (_, i) => String(thisYear - i))

/** 教辅题按篇章分段（本页内相邻的同篇章题放在一起） */
function bySection(cards: BankCard[]) {
  const groups: { section: string; cards: BankCard[] }[] = []
  for (const card of cards) {
    const section = bookSection(card.book)
    const last = groups.at(-1)
    if (last && last.section === section) last.cards.push(card)
    else groups.push({ section, cards: [card] })
  }
  return groups
}

/**
 * 题库浏览：先选题集（不同题集不混放），真题再按类别、年份筛选；都可以按考点筛选。
 * 地址栏保存题集、筛选、页码和打开的题（?open=题目编号），地址栏保存筛选、页码和打开的题（?open=题目编号），
 * 方便从考点页直接跳到某道题。
 */
export function BankPage() {
  const [params, setParams] = useSearchParams()
  const { data: collections, error: collectionsError } = useBankCollections()
  const asked = params.get('collection')
  // 没有题的题集不显示（除非地址里正好指定了它）；默认真题
  const shown = (collections ?? []).filter((c) => c.total > 0 || c.id === asked)
  const collection =
    shown.find((c) => c.id === asked) ?? shown.find((c) => c.id === 'zhenti') ?? shown[0]
  // 题集列表还没回来时先按地址（默认真题）取题，两个请求并行，首屏更快
  const loaded = collections !== undefined
  const collectionId = loaded ? (collection?.id ?? '') : (asked ?? 'zhenti')
  const isExam = loaded ? collection?.kind === 'exam' : collectionId === 'zhenti'
  // 第二层：本题集里有题的数学类别（接口还没给 math_types 时，真题按三类显示）
  const mathTypes = collection?.math_types
    ? collection.math_types.filter((m) => m.total > 0).map((m) => String(m.math_type))
    : isExam
      ? ['1', '2', '3']
      : []
  const askedType = params.get('math_type') ?? ''
  const filter: BankFilter = {
    collection: collectionId,
    mathType: mathTypes.includes(askedType) ? askedType : '',
    year: isExam ? (params.get('year') ?? '') : '',
    topic: params.get('topic') ?? '',
  }
  const page = Math.max(1, Number(params.get('page')) || 1)
  const openId = params.get('open')
  const { data, isLoading, isError, error, isPlaceholderData } = useBank(
    filter,
    (page - 1) * pageSize,
    pageSize,
  )
  const { data: topic } = useTopic(filter.topic || undefined)
  // 真题本页内按年份、类别、题号排列；教辅题保持接口顺序，按篇章分段
  const items = useMemo(
    () =>
      isExam
        ? [...(data?.items ?? [])].sort(
            (a, b) =>
              Number(b.year) - Number(a.year) || a.math_type - b.math_type || a.number - b.number,
          )
        : (data?.items ?? []),
    [data, isExam],
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
      <PageHeader
        title="题库"
        subtitle="按题集和数学类别浏览；真题还可以按年份筛选，都能按考点筛选。"
      />
      {shown.length > 1 && collection && (
        <div className={styles.collections}>
          <Segmented<string>
            label="题集"
            items={shown.map((c) => ({ value: c.id, label: c.name }))}
            value={collection.id}
            onChange={(value) => update({ collection: value, math_type: '', year: '' })}
          />
        </div>
      )}
      <Card className={styles.filters} aria-label="筛选">
        {collection && !isExam && <span className={styles.collectionName}>{collection.name}</span>}
        {mathTypes.length > 0 && (
          <Segmented<string>
            label="数学类别"
            items={[
              { value: '', label: '全部' },
              ...mathTypes.map((type) => ({ value: type, label: typeLabel[type] ?? type })),
            ]}
            value={filter.mathType}
            onChange={(value) => update({ math_type: value })}
          />
        )}
        {isExam && (
          <>
            <label className={styles.yearField}>
              年份
              <select
                value={filter.year}
                onChange={(event) => update({ year: event.target.value })}
              >
                <option value="">全部年份</option>
                {years.map((year) => (
                  <option key={year} value={year}>
                    {year}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
        {collection && (
          <TopicSearch scope={collection.name} onPick={(id) => update({ topic: id })} />
        )}
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

      {(isError || collectionsError) && (
        <Card padded className={styles.notice}>
          {(error ?? collectionsError)?.message}
        </Card>
      )}
      {collections && !collection && (
        <Card padded className={styles.notice}>
          题库里还没有题目。
        </Card>
      )}
      {(isLoading || (!collections && !data)) && !collectionsError && (
        <Card padded className={styles.notice}>
          正在读取…
        </Card>
      )}
      {data && data.total === 0 && (
        <Card padded className={styles.notice}>
          {isExam
            ? '没有符合条件的题目，换个类别或年份试试。'
            : '没有符合条件的题目，换个类别试试。'}
        </Card>
      )}
      <div style={{ opacity: isPlaceholderData ? 0.6 : 1 }}>
        {(isExam ? [{ section: '', cards: items }] : bySection(items)).map((group, index) => (
          <section key={`${index}-${group.section}`} className={styles.group}>
            {group.section && <h2 className={styles.section}>{group.section}</h2>}
            <div className={styles.grid}>
              {group.cards.map((card) => (
                <BankQuestionCard
                  key={card.id}
                  card={card}
                  topics={topicsOf(card.id)}
                  onOpen={() => update({ open: card.id, page: String(page) })}
                />
              ))}
            </div>
          </section>
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
