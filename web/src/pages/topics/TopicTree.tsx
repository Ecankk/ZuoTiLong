import { ChevronRight } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import type { CatalogNode } from '../../api/types'
import { ancestors, type CatalogIndex } from '../../lib/catalog'
import { cx } from '../../lib/cx'
import styles from './TopicsPage.module.css'

/** 考点树：只渲染展开的分支（目录约 1000 项）。选中项的上级自动展开。 */
export function TopicTree({ index, selected }: { index: CatalogIndex; selected?: string }) {
  // 用户手动展开/收起的记录；没记录时，根节点和选中项的上级默认展开
  const [overrides, setOverrides] = useState<Map<string, boolean>>(() => new Map())
  const defaults = useMemo(
    () =>
      new Set([
        ...index.roots.map((node) => node.id),
        ...(selected ? ancestors(index, selected).map((node) => node.id) : []),
      ]),
    [index, selected],
  )
  const listRef = useRef<HTMLUListElement>(null)
  // 选中的考点滚到可视区域（只操作 DOM，不改状态）
  useEffect(() => {
    listRef.current?.querySelector('[aria-current="page"]')?.scrollIntoView({ block: 'nearest' })
  }, [selected])
  const expanded = { has: (id: string) => overrides.get(id) ?? defaults.has(id) }
  const toggle = (id: string) =>
    setOverrides((before) => new Map(before).set(id, !expanded.has(id)))

  const renderNode = (node: CatalogNode, depth: number) => {
    const kids = index.children.get(node.id) ?? []
    const open = expanded.has(node.id)
    return (
      <li key={node.id}>
        <div
          className={cx(styles.node, node.id === selected && styles.selected)}
          style={{ paddingLeft: 4 + depth * 14 }}
        >
          {kids.length > 0 ? (
            <button
              type="button"
              className={cx(styles.toggle, open && styles.open)}
              aria-label={`${open ? '收起' : '展开'}${node.name}`}
              aria-expanded={open}
              onClick={() => toggle(node.id)}
            >
              <ChevronRight size={14} aria-hidden />
            </button>
          ) : (
            <span className={styles.leaf} aria-hidden />
          )}
          <Link
            to={`/topics/${encodeURIComponent(node.id)}`}
            className={cx(styles.nodeLink, node.kind !== 'atom' && styles.group)}
            aria-current={node.id === selected ? 'page' : undefined}
          >
            {node.name}
          </Link>
          {kids.length > 0 && <span className={styles.childCount}>{kids.length}</span>}
        </div>
        {open && kids.length > 0 && <ul>{kids.map((kid) => renderNode(kid, depth + 1))}</ul>}
      </li>
    )
  }
  return (
    <ul ref={listRef} className={styles.tree}>
      {index.roots.map((node) => renderNode(node, 0))}
    </ul>
  )
}
