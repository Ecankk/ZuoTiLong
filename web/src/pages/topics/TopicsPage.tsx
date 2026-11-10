import { ChevronRight, Search } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router'
import { useBank, useBankCollections, useCatalog, usePractices, useTopic } from '../../api/queries'
import type { TopicResponse } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { ButtonLink } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { ErrorState } from '../../components/ui/ErrorState'
import { Chip, type ChipTone } from '../../components/ui/Chip'
import { PageHeader } from '../../components/ui/PageHeader'
import { Skeleton } from '../../components/ui/Skeleton'
import {
  ancestors,
  buildCatalog,
  kindLabel,
  searchCatalog,
  type CatalogIndex,
} from '../../lib/catalog'
import { bankTitle, hiddenCollection, practiceLink } from '../bank/BankQuestion'
import { TopicName } from './TopicName'
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
              <strong>
                <TopicName name={node.name} />
              </strong>
              <small>{path.map((p) => p.name).join(' / ') || kindLabel(node.kind)}</small>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

/** 按来源拆分：原卷、对口练习是做题记录数（和上面的做对、做错、待定是同一批）；自由练习是整题作答次数。 */
function SourceCounts({
  counts,
}: {
  counts: NonNullable<TopicResponse['performance']['source_counts']>
}) {
  const free = counts.free_practice
  return (
    <section className={styles.sources} aria-label="按来源">
      <h4>按来源</h4>
      <dl>
        <div>
          <dt>原卷</dt>
          <dd>{counts.exam} 条做题记录</dd>
        </div>
        <div>
          <dt>对口练习</dt>
          <dd>{counts.practice} 条做题记录</dd>
        </div>
        <div>
          <dt>自由练习</dt>
          <dd>
            {free.total} 次
            {free.total > 0 && (
              <small>
                {[
                  `独立做对 ${free.independent_correct}`,
                  `看过答案后做对 ${free.assisted_correct}`,
                  `做错 ${free.wrong}`,
                  free.pending > 0 ? `待批改 ${free.pending}` : '',
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </small>
            )}
          </dd>
        </div>
      </dl>
      {free.total > 0 && (
        <p className={styles.muted}>
          自由练习按整题记录，用来参考；做对一次不代表已经掌握这个考点。
        </p>
      )}
    </section>
  )
}

/**
 * 题库中的关联题：按题集分开看，题数来自 collection_counts（各题集分别计数，不相加）。
 */
function RelatedQuestions({
  topicId,
  counts,
}: {
  topicId: string
  counts: TopicResponse['collection_counts']
}) {
  const { data: collections } = useBankCollections()
  // 按题集的显示顺序排列，只列有关联题的题集
  const groups = (collections ?? [])
    .map((c) => ({ ...c, bank: counts.find((n) => n.collection_id === c.id)?.bank ?? 0 }))
    .filter((c) => c.bank > 0 && c.id !== hiddenCollection)
  const [picked, setPicked] = useState<string | null>(null)
  const current = groups.find((c) => c.id === picked) ?? groups[0]
  const { data } = useBank(
    { collection: current?.id ?? '', mathType: '', year: '', topic: topicId },
    0,
    6,
  )
  if (!collections) return <p className={styles.muted}>正在读取…</p>
  if (!current) return <p className={styles.muted}>题库里还没有关联到这个考点的题目。</p>
  const bankLink = `/bank?collection=${encodeURIComponent(current.id)}&topic=${encodeURIComponent(topicId)}`
  return (
    <>
      <div className={styles.collectionTabs} role="group" aria-label="题集">
        {groups.map((c) => (
          <button
            key={c.id}
            type="button"
            aria-pressed={c.id === current.id}
            onClick={() => setPicked(c.id)}
          >
            {c.name} <span>{c.bank} 题</span>
          </button>
        ))}
      </div>
      <ul className={styles.related}>
        {data?.items.map((card) => (
          <li key={card.id}>
            <Link to={`${bankLink}&open=${encodeURIComponent(card.id)}`}>
              {bankTitle(card) || '题目（未标注题号）'}
              {card.question_type && <small>{card.question_type}</small>}
            </Link>
            {card.can_view && !card.reserved && (
              <Link className={styles.doIt} to={practiceLink(card.id)}>
                做这道题
              </Link>
            )}
          </li>
        ))}
      </ul>
      <ButtonLink size="sm" to={bankLink}>
        在题库中查看{current.name}的全部 {current.bank} 题
      </ButtonLink>
    </>
  )
}

function TopicDetail({ index, topicId }: { index: CatalogIndex; topicId: string }) {
  const { data, isPending, isError, error, refetch } = useTopic(topicId)
  if (isPending)
    return (
      <div className={styles.detail}>
        <Skeleton rows={4} />
        <Skeleton rows={3} />
      </div>
    )
  if (isError)
    return <ErrorState error={error} title="没能读取这个考点" onRetry={() => void refetch()} />
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
  const recorded = performance.successes + performance.failures + performance.pending
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
        <h2>
          <TopicName name={topic.name} />
        </h2>
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
          </dl>
          <p className={styles.muted}>
            {`按这个考点用得对不对统计，共 ${recorded} 条做题记录。待定：结果还没核对。`}
          </p>
          {counts.completed > 0 && (
            <p className={styles.muted}>
              {`试卷里有 ${counts.completed} 道题涉及这个考点。题目做错不一定错在这里，所以和上面的数字可能不同。`}
            </p>
          )}
          {performance.source_counts && <SourceCounts counts={performance.source_counts} />}
          {practiceActive > 0 && (
            <ButtonLink size="sm" to={`/practice?topic=${encodeURIComponent(topic.id)}`}>
              这个考点的练习：{practice.pending} 道待做
            </ButtonLink>
          )}
        </Card>
        <Card padded aria-label="题库中的相关题目">
          <h3>题库中的相关题目</h3>
          <RelatedQuestions
            key={topic.id}
            topicId={topic.id}
            counts={data.collection_counts ?? []}
          />
        </Card>
      </div>

      {kids.length > 0 && (
        <Card padded aria-label="包含的考点">
          <h3>包含的考点</h3>
          <div className={styles.kids}>
            {kids.map((kid) => (
              <Link key={kid.id} to={`/topics/${encodeURIComponent(kid.id)}`}>
                <Chip tone={kid.kind === 'atom' ? 'plain' : 'primary'}>
                  <TopicName name={kid.name} />
                </Chip>
              </Link>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

/** 每个考点最多列出的数量 */
const weakLimit = 10

/**
 * 没选考点时：列出有待做练习的考点（练习是按试卷里的薄弱考点准备的），给出明确的下一步。
 */
function TopicsHome() {
  const { data, isError } = usePractices('topic')
  const groups = (data?.items ?? [])
    .filter((group) => group.counts.pending > 0)
    .sort((a, b) => b.counts.pending - a.counts.pending)
  return (
    <Card padded aria-label="我的薄弱考点" className={styles.home}>
      <h3>我的薄弱考点</h3>
      {groups.length > 0 ? (
        <>
          <p className={styles.muted}>
            这些考点在你的试卷里出过问题，做题龙已经准备了练习。点开可以看定义、易混点和相关题目。
          </p>
          <ul className={styles.weak}>
            {groups.slice(0, weakLimit).map((group) => (
              <li key={group.id}>
                <Link to={`/topics/${encodeURIComponent(group.id)}`}>
                  <TopicName name={group.label} />
                </Link>
                <small>{group.counts.pending} 道待做</small>
              </li>
            ))}
          </ul>
          <ButtonLink size="sm" variant="primary" to="/practice">
            {groups.length > weakLimit
              ? `去练习（还有 ${groups.length - weakLimit} 个考点）`
              : '去练习'}
          </ButtonLink>
        </>
      ) : (
        <p className={styles.muted}>
          {isError
            ? '暂时读不到你的练习，可以先从左侧目录浏览，或搜索考点名称。'
            : data
              ? '分析完试卷后，你出过错的考点会列在这里。现在可以从左侧目录浏览，或搜索考点名称。'
              : '正在读取…'}
        </p>
      )}
    </Card>
  )
}

export function TopicsPage() {
  const { topicId } = useParams()
  const { data: nodes, isPending, isError, error, refetch } = useCatalog()
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
            {isError && (
              <ErrorState
                inline
                error={error}
                title="没能读取考点目录"
                onRetry={() => void refetch()}
              />
            )}
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
          {topicId && index ? <TopicDetail index={index} topicId={topicId} /> : <TopicsHome />}
        </div>
      </div>
    </>
  )
}
