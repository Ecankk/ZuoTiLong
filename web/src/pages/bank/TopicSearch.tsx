import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useCatalog } from '../../api/queries'
import { ancestors, buildCatalog, searchCatalog } from '../../lib/catalog'
import styles from './BankPage.module.css'

/**
 * 题库搜索框：输入时列出匹配的考点（名称或别名），选中后设为考点筛选；
 * 回车或选“搜索题面”时按题面文字搜索。两者都在当前题集和类别内。
 * 考点目录在第一次点开输入框时才读取，不拖慢题库首屏。
 */
export function TopicSearch({
  scope,
  onPick,
  onText,
}: {
  scope: string
  onPick: (id: string) => void
  onText: (text: string) => void
}) {
  const [wanted, setWanted] = useState(false)
  const [query, setQuery] = useState('')
  const { data: nodes, isPending } = useCatalog(wanted)
  const index = useMemo(() => (nodes ? buildCatalog(nodes) : null), [nodes])
  const term = query.trim()
  const results = index && term ? searchCatalog(index, term, 8) : []

  return (
    <div className={styles.topicSearch}>
      <label>
        <Search size={15} aria-hidden />
        <input
          type="search"
          aria-label="搜索考点或题面"
          placeholder={`在${scope}里搜考点或题面文字`}
          value={query}
          onFocus={() => setWanted(true)}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setQuery('')
            if (event.key === 'Enter' && term) {
              onText(term)
              setQuery('')
            }
          }}
        />
      </label>
      {term && (
        <div className={styles.topicResults} role="group" aria-label="搜索建议">
          <button
            type="button"
            className={styles.textSearch}
            onClick={() => {
              onText(term)
              setQuery('')
            }}
          >
            <strong>搜索题面：{term}</strong>
            <small>按回车也可以</small>
          </button>
          {!index && isPending && <p>正在读取考点目录…</p>}
          {index && results.length === 0 && <p>没有找到“{term}”相关的考点。</p>}
          {results.map((node) => (
            <button
              key={node.id}
              type="button"
              onClick={() => {
                onPick(node.id)
                setQuery('')
              }}
            >
              <strong>{node.name}</strong>
              <small>
                {ancestors(index!, node.id)
                  .map((p) => p.name)
                  .join(' / ')}
              </small>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
