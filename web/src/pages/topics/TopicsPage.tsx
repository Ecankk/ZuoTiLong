import { ChevronRight, Search } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router'
import { useBank, useCatalog, useTopic } from '../../api/queries'
import { MathText } from '../../components/math/MathText'
import { ButtonLink } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip, type ChipTone } from '../../components/ui/Chip'
import { PageHeader } from '../../components/ui/PageHeader'
import {
  ancestors,
  buildCatalog,
  kindLabel,
  searchCatalog,
  type CatalogIndex,
} from '../../lib/catalog'
import { bankTitle } from '../bank/BankQuestion'
import { TopicTree } from './TopicTree'
import styles from './TopicsPage.module.css'

/** 个人表现的状态文字来自后端；只有“需要关注”标成提醒色，其余中性显示。 */
const stateTone = (state: string): ChipTone =>
  state === '需要关注' ? 'wrong' : state === '已掌握' || state === '稳定' ? 'correct' : 'unknown'

function SearchResults({ index, query }: { index: CatalogIndex; query: string }) {
  const results = searchCatalog(index, query)
  if (!results.length) return <p className={styles.empty}>没有找到“{query}”相关的考点。</p>
  return (
    <ul className={styles.results}>
      {results.map((node) => {
        const path = ancestors(index, node.id)
        return (
          <li key={node.id}>
            <Link to={`/topics/${encodeURIComponent(node.id)}`}>
              <strong>{node.name}</strong>
              <small>{path.map((p) => p.name).join(' / ') || kindLabel(node.kind)}</small>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

function RelatedQuestions({ topicId, total }: { topicId: string; total: number }) {
  const { data } = useBank({ mathType: '', year: '', topic: topicId }, 0, 6)
  if (!total) return <p className={styles.muted}>题库里还没有关联到这个考点的题目。</p>
  return (
    <>
      <ul className={styles.related}>
        {data?.items.map((card) => (
          <li key={card.id}>
            <Link
              to={`/bank?math_type=${card.math_type}&year=${card.year}&open=${encodeURIComponent(card.id)}`}
            >
              {bankTitle(card)}
              {card.question_type && <small>{card.question_type}</small>}
            </Link>
          </li>
        ))}
      </ul>
      <ButtonLink size="sm" to={`/bank?topic=${encodeURIComponent(topicId)}`}>
        在题库中查看全部 {total} 题
      </ButtonLink>
    </>
  )
}

function TopicDetail({ index, topicId }: { index: CatalogIndex; topicId: string }) {
  const { data, isPending, isError, error } = useTopic(topicId)
  if (isPending)
    return (
      <Card padded className={styles.muted}>
        正在读取…
      </Card>
    )
  if (isError)
    return (
      <Card padded className={styles.muted}>
        {error.message}
      </Card>
    )
  if (!data)
    return (
      <Card padded className={styles.muted}>
        目录里没有这个考点，可能已经调整。可以在左侧搜索名称重新查找。
      </Card>
    )
  // 历史考点编号：后端返回新的考点，地址同步过去
  if (data.topic.id !== topicId)
    return <Navigate replace to={`/topics/${encodeURIComponent(data.topic.id)}`} />

  const { topic, performance, question_counts: counts, practice_counts: practice } = data
  const node = index.byId.get(topic.id)
  const path = ancestors(index, topic.id)
  const kids = index.children.get(topic.id) ?? []
  const practiceActive = practice.total - practice.inactive
  return (
    <div className={styles.detail}>
      <Card padded>
        <nav aria-label="考点位置" className={styles.path}>
          {path.map((p, i) => (
            <Fragment key={p.id}>
              {i > 0 && <ChevronRight size={12} aria-hidden />}
              <Link to={`/topics/${encodeURIComponent(p.id)}`}>{p.name}</Link>
            </Fragment>
          ))}
        </nav>
        <span className={styles.kind}>{kindLabel(topic.kind)}</span>
        <h2>{topic.name}</h2>
        {node?.aliases?.length ? (
          <p className={styles.muted}>也叫：{node.aliases.join('、')}</p>
        ) : null}
        {topic.definition ? (
          <div className="read" style={{ marginTop: 'var(--space-3)' }}>
            <MathText text={topic.definition} implicit />
          </div>
        ) : (
          kids.length > 0 && <p className={styles.muted}>这是一组考点，下面列出了包含的内容。</p>
        )}
        {topic.conditions.length > 0 && (
          <section className={styles.section}>
            <h3>适用条件</h3>
            <ul className="read">
              {topic.conditions.map((text, i) => (
                <li key={i}>
                  <MathText text={text} implicit />
                </li>
              ))}
            </ul>
          </section>
        )}
        {topic.boundaries.length > 0 && (
          <section className={styles.section}>
            <h3>边界与易混点</h3>
            <ul className="read">
              {topic.boundaries.map((text, i) => (
                <li key={i}>
                  <MathText text={text} implicit />
                </li>
              ))}
            </ul>
          </section>
        )}
      </Card>

      <div className={styles.columns}>
        <Card padded aria-label="我的做题情况">
          <h3>我的做题情况</h3>
          <div className={styles.stateRow}>
            <Chip tone={stateTone(performance.state)}>{performance.state}</Chip>
          </div>
          <p className={styles.muted}>{performance.state_reason}</p>
          <dl className={styles.stats}>
            <div>
              <dt>做对</dt>
              <dd>{performance.successes}</dd>
            </div>
            <div>
              <dt>做错</dt>
              <dd>{performance.failures}</dd>
            </div>
            <div>
              <dt>待定</dt>
              <dd>{performance.pending}</dd>
            </div>
            <div>
              <dt>已做题</dt>
              <dd>{counts.completed}</dd>
            </div>
          </dl>
          {practiceActive > 0 && (
            <ButtonLink size="sm" to={`/practice?topic=${encodeURIComponent(topic.id)}`}>
              这个考点的练习：{practice.pending} 道待做
            </ButtonLink>
          )}
        </Card>
        <Card padded aria-label="题库中的相关题目">
          <h3>题库中的相关题目</h3>
          <RelatedQuestions topicId={topic.id} total={counts.bank} />
        </Card>
      </div>

      {kids.length > 0 && (
        <Card padded aria-label="包含的考点">
          <h3>包含的考点</h3>
          <div className={styles.kids}>
            {kids.map((kid) => (
              <Link key={kid.id} to={`/topics/${encodeURIComponent(kid.id)}`}>
                <Chip tone={kid.kind === 'atom' ? 'plain' : 'primary'}>{kid.name}</Chip>
              </Link>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

export function TopicsPage() {
  const { topicId } = useParams()
  const { data: nodes, isPending, isError, error } = useCatalog()
  const index = useMemo(() => (nodes ? buildCatalog(nodes) : null), [nodes])
  const [query, setQuery] = useState('')
  return (
    <>
      <PageHeader title="考点" subtitle="按章节浏览考点，查看定义、适用条件和你的做题情况。" />
      <div className={styles.layout}>
        <Card className={styles.sidebar} aria-label="考点目录">
          <label className={styles.search}>
            <Search size={16} aria-hidden />
            <input
              type="search"
              placeholder="搜索考点名称或别名"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <div className={styles.treeScroll}>
            {isPending && <p className={styles.empty}>正在读取目录…</p>}
            {isError && <p className={styles.empty}>{error.message}</p>}
            {index &&
              (query.trim() ? (
                <SearchResults index={index} query={query} />
              ) : (
                <TopicTree index={index} selected={topicId} />
              ))}
          </div>
          {nodes && <p className={styles.total}>共 {nodes.length} 个目录项</p>}
        </Card>
        <div>
          {topicId && index ? (
            <TopicDetail index={index} topicId={topicId} />
          ) : (
            <Card padded className={styles.muted}>
              从左侧选择一个考点，或搜索名称。
            </Card>
          )}
        </div>
      </div>
    </>
  )
}
