import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useCatalog } from '../../api/queries'
import { ancestors, buildCatalog, searchCatalog } from '../../lib/catalog'
import styles from './BankPage.module.css'

/**
 * 按考点找题：在考点目录里搜名称或别名，选中后设为题库的考点筛选（仍在当前题集内）。
 * 目录在第一次点开输入框时才读取，不拖慢题库首屏。
 */
export function TopicSearch({ scope, onPick }: { scope: string; onPick: (id: string) => void }) {
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
          aria-label="按考点找题"
          placeholder={`在${scope}里按考点找题`}
          value={query}
          onFocus={() => setWanted(true)}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => event.key === 'Escape' && setQuery('')}
        />
      </label>
      {term && (
        <div className={styles.topicResults} role="group" aria-label="考点搜索结果">
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
