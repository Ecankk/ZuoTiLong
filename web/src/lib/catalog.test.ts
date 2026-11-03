import { expect, it } from 'vitest'
import type { CatalogNode } from '../api/types'
import { ancestors, buildCatalog, kindLabel, searchCatalog } from './catalog'

const node = (
  id: string,
  parent: string | null,
  kind: string,
  name: string,
  aliases: string[] = [],
) => ({ id, parent_id: parent, kind, name, aliases }) as CatalogNode

const nodes = [
  node('a1', 'ch', 'atom', '等价无穷小替换', ['等价代换']),
  node('math1', null, 'subject', '高等数学'),
  node('ch', 'math1', 'chapter', '函数与极限'),
  node('t1', 'ch', 'topic', '无穷小的比较'),
  node('orphan', 'missing', 'atom', '孤立考点'),
]

it('builds a tree with groups before topics and orphans as roots', () => {
  const index = buildCatalog(nodes)
  expect(index.roots.map((n) => n.id)).toEqual(['math1', 'orphan'])
  expect(index.children.get('ch')?.map((n) => n.id)).toEqual(['t1', 'a1'])
  expect(ancestors(index, 'a1').map((n) => n.id)).toEqual(['math1', 'ch'])
})

it('searches names first, then aliases', () => {
  const index = buildCatalog(nodes)
  expect(searchCatalog(index, '无穷小').map((n) => n.id)).toEqual(['a1', 't1'])
  expect(searchCatalog(index, '代换').map((n) => n.id)).toEqual(['a1'])
  expect(searchCatalog(index, '  ')).toEqual([])
})

it('never shows the internal word for leaf topics', () => {
  expect(kindLabel('atom')).toBe('考点')
})
