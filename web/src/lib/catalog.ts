import type { CatalogNode } from '../api/types'

export type CatalogIndex = {
  byId: Map<string, CatalogNode>
  children: Map<string | null, CatalogNode[]>
  roots: CatalogNode[]
}

const kindOrder: Record<string, number> = { subject: 0, chapter: 1, topic: 2, atom: 3 }

/** 按 parent_id 建树；父节点不在目录里的当作根。同级先放分组再放考点，保持目录原顺序。 */
export function buildCatalog(nodes: CatalogNode[]): CatalogIndex {
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const children = new Map<string | null, CatalogNode[]>()
  nodes.forEach((node) => {
    const parent = node.parent_id && byId.has(node.parent_id) ? node.parent_id : null
    const list = children.get(parent) ?? []
    list.push(node)
    children.set(parent, list)
  })
  for (const list of children.values())
    list.sort((a, b) => (kindOrder[a.kind] ?? 9) - (kindOrder[b.kind] ?? 9))
  return { byId, children, roots: children.get(null) ?? [] }
}

/** 从根到该节点的路径（不含自身） */
export function ancestors(index: CatalogIndex, id: string): CatalogNode[] {
  const path: CatalogNode[] = []
  const seen = new Set<string>()
  let current = index.byId.get(id)?.parent_id
  while (current && index.byId.has(current) && !seen.has(current)) {
    seen.add(current)
    const node = index.byId.get(current)!
    path.unshift(node)
    current = node.parent_id
  }
  return path
}

/** 名称或别名包含关键词；名称命中的排前面 */
export function searchCatalog(index: CatalogIndex, query: string, limit = 80): CatalogNode[] {
  const term = query.trim().toLowerCase()
  if (!term) return []
  const byName: CatalogNode[] = []
  const byAlias: CatalogNode[] = []
  for (const node of index.byId.values()) {
    if (node.name.toLowerCase().includes(term)) byName.push(node)
    else if (node.aliases?.some((alias) => alias.toLowerCase().includes(term))) byAlias.push(node)
  }
  return [...byName, ...byAlias].slice(0, limit)
}

export const kindLabel = (kind: string) =>
  ({ subject: '学科', chapter: '章节', topic: '考点组' })[kind] ?? '考点'
