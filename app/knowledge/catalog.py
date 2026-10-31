"""Versioned, explicitly maintained knowledge definitions; no learner judgments."""
from app.storage.boundaries import table_exists
import copy
import hashlib
import json
import re
import unicodedata
import uuid
from contextlib import contextmanager

SCHEMA_VERSION = 'mathlens.knowledge-catalog/v1'
NODE_KINDS = ('subject', 'chapter', 'topic', 'atom')
DISPOSITIONS = ('mapped', 'method', 'navigation', 'excluded', 'pending')
ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9:._-]{0,199}$')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum())


@contextmanager
def atomic(conn):
    name = 'catalog_' + uuid.uuid4().hex
    conn.execute('SAVEPOINT ' + name)
    try:
        yield
    except BaseException:
        conn.execute('ROLLBACK TO ' + name)
        conn.execute('RELEASE ' + name)
        raise
    else:
        conn.execute('RELEASE ' + name)


def initialize(conn):
    for sql in (
        '''CREATE TABLE IF NOT EXISTS knowledge_source_versions(
        id TEXT PRIMARY KEY,source TEXT NOT NULL,revision TEXT NOT NULL,
        manifest_sha256 TEXT NOT NULL,metadata_json TEXT NOT NULL,UNIQUE(source,revision))''',
        '''CREATE TABLE IF NOT EXISTS knowledge_source_entries(
        source_version_id TEXT NOT NULL REFERENCES knowledge_source_versions(id),
        id TEXT NOT NULL,kind TEXT NOT NULL,content_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,
        PRIMARY KEY(source_version_id,id))''',
        '''CREATE TABLE IF NOT EXISTS knowledge_catalog_releases(
        id TEXT PRIMARY KEY,parent_id TEXT REFERENCES knowledge_catalog_releases(id),
        state TEXT NOT NULL,document_json TEXT NOT NULL,content_sha256 TEXT NOT NULL,
        reviewer TEXT,published_at TEXT)''',
        '''CREATE TABLE IF NOT EXISTS knowledge_catalog_state(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        release_id TEXT NOT NULL REFERENCES knowledge_catalog_releases(id))''',
        '''CREATE TABLE IF NOT EXISTS knowledge_catalog_nodes(
        release_id TEXT NOT NULL REFERENCES knowledge_catalog_releases(id),id TEXT NOT NULL,
        parent_id TEXT,name TEXT NOT NULL,kind TEXT NOT NULL,payload_json TEXT NOT NULL,
        PRIMARY KEY(release_id,id))''',
        '''CREATE TABLE IF NOT EXISTS knowledge_catalog_redirects(
        release_id TEXT NOT NULL REFERENCES knowledge_catalog_releases(id),
        old_id TEXT NOT NULL,target_id TEXT NOT NULL,reason TEXT NOT NULL,
        PRIMARY KEY(release_id,old_id))''',
    ):
        conn.execute(sql)
    from app.storage.catalog_packages import initialize as initialize_packages
    initialize_packages(conn)


def active_id(conn):
    if not table_exists(conn, 'knowledge_catalog_state'):
        return None
    row = conn.execute('SELECT release_id FROM knowledge_catalog_state WHERE singleton=1').fetchone()
    return row[0] if row else None


def document(conn, release_id=None):
    release_id = release_id or active_id(conn)
    if not release_id:
        return None
    row = conn.execute('SELECT * FROM knowledge_catalog_releases WHERE id=?', (release_id,)).fetchone()
    if not row:
        raise ValueError('知识目录版本不存在')
    return {'id': row['id'], 'state': row['state'], 'parent_id': row['parent_id'],
            'content_sha256': row['content_sha256'], 'document': json.loads(row['document_json'])}


def base_document(conn):
    current = document(conn)
    if current:
        return copy.deepcopy(current['document'])
    from app.knowledge.index import catalog
    return {'schema_version': SCHEMA_VERSION, 'label': '项目基础学习目录',
            'nodes': [{'id': n['id'], 'parent_id': n['parent_id'], 'name': n['name'],
                       'kind': 'subject' if not n['parent_id'] else 'chapter',
                       'definition': n['name'], 'conditions': [],
                       'boundaries': ['粗目录分类，不表示原子覆盖完整或学生已掌握。'],
                       'aliases': n['aliases'], 'math_types': [], 'source_refs': [],
                       'review_note': '沿用项目历史粗目录，不宣称当年官方完整考纲。'} for n in catalog(conn)],
            'redirects': [], 'source_resolutions': [], 'limitations': []}


def _text(value, name, maximum=16000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(name + '须为非空且长度合法的文字')


def validate(conn, value):
    fields = {'schema_version', 'label', 'nodes', 'redirects', 'source_resolutions', 'limitations'}
    if not isinstance(value, dict) or set(value) != fields or value['schema_version'] != SCHEMA_VERSION:
        raise ValueError('目录文档字段或版本不合法')
    _text(value['label'], '目录名称', 200)
    if not isinstance(value['nodes'], list) or not value['nodes']:
        raise ValueError('知识目录不能是空目录')
    node_fields = {'id', 'parent_id', 'name', 'kind', 'definition', 'conditions', 'boundaries',
                   'aliases', 'math_types', 'source_refs', 'review_note'}
    from app.storage.catalog_packages import source_known
    nodes, names = {}, {}
    for node in value['nodes']:
        if not isinstance(node, dict) or set(node) != node_fields:
            raise ValueError('知识节点字段不完整或包含未知字段')
        nid = node['id']
        if not isinstance(nid, str) or not ID.fullmatch(nid) or nid in nodes:
            raise ValueError('知识节点ID不合法或重复')
        if node['kind'] not in NODE_KINDS:
            raise ValueError('节点类型必须是知识目录类型，方法和表现另存')
        for field, limit in (('name', 160), ('definition', 16000), ('review_note', 4000)):
            _text(node[field], field, limit)
        key = normalized(node['name'])
        if not key or key in names:
            raise ValueError('存在同名或格式等价的规范考点，须先核对同义/条件边界')
        names[key] = nid
        for field in ('conditions', 'boundaries', 'aliases'):
            if not isinstance(node[field], list) or any(not isinstance(s, str) or not s.strip() for s in node[field]):
                raise ValueError(field + '须为非空文字组成的数组')
        if not isinstance(node['math_types'], list) or any(type(t) is not int or t not in (1, 2, 3) for t in node['math_types']):
            raise ValueError('数学适用范围不合法；待核范围可留空')
        if node['parent_id'] is not None and (not isinstance(node['parent_id'], str) or not ID.fullmatch(node['parent_id'])):
            raise ValueError('父节点ID不合法')
        if not isinstance(node['source_refs'], list) or node['kind'] == 'atom' and not node['source_refs']:
            raise ValueError('原子须有真实来源引用')
        for ref in node['source_refs']:
            if not isinstance(ref, dict) or set(ref) != {'source_version_id', 'source_id'}:
                raise ValueError('来源引用字段不合法')
            if any(not isinstance(ref[k], str) or not ID.fullmatch(ref[k]) for k in ref):
                raise ValueError('来源引用ID不合法')
            if not source_known(conn, ref['source_version_id'], ref['source_id']):
                raise ValueError('目录引用不存在的候选来源')
        nodes[nid] = node
    for node in nodes.values():
        seen = {node['id']};parent = node['parent_id']
        while parent is not None:
            if parent not in nodes or parent in seen:
                raise ValueError('知识树存在断链或循环')
            seen.add(parent);parent = nodes[parent]['parent_id']
        if node['kind'] != 'subject' and node['parent_id'] is None:
            raise ValueError('非学科知识节点须有明确父节点')
    redirects = {}
    if not isinstance(value['redirects'], list):raise ValueError('重定向须为数组')
    for link in value['redirects']:
        if not isinstance(link, dict) or set(link) != {'old_id', 'target_id', 'reason'}:
            raise ValueError('知识重定向字段不合法')
        old, target = link['old_id'], link['target_id']
        if not isinstance(old, str) or not ID.fullmatch(old) or not isinstance(target, str) or old in nodes or old in redirects or target not in nodes:
            raise ValueError('重定向重复、循环或目标不存在；合并须直接指向有效节点')
        _text(link['reason'], '合并依据');redirects[old] = target
    current = document(conn)
    historical = ({n['id'] for n in current['document']['nodes']} | {r['old_id'] for r in current['document']['redirects']}
                  if current else {r[0] for r in conn.execute('SELECT id FROM knowledge_nodes')})
    if not historical.issubset(set(nodes) | set(redirects)):
        raise ValueError('新版本不能丢弃历史考点ID；须保留节点或重定向')
    seen = set(); resolutions = {}
    if not isinstance(value['source_resolutions'], list):raise ValueError('来源处置须为数组')
    for item in value['source_resolutions']:
        if not isinstance(item, dict) or set(item) != {'source_version_id', 'source_id', 'disposition', 'node_ids', 'reason'}:
            raise ValueError('来源处置字段不合法')
        if any(not isinstance(item[k], str) or not ID.fullmatch(item[k]) for k in ('source_version_id', 'source_id')):
            raise ValueError('来源处置ID不合法')
        key = (item['source_version_id'], item['source_id'])
        if key in seen or not source_known(conn, *key):
            raise ValueError('来源处置重复或引用不存在的记录')
        seen.add(key)
        if (item['disposition'] not in DISPOSITIONS or not isinstance(item['node_ids'], list)
                or any(not isinstance(n, str) for n in item['node_ids']) or not set(item['node_ids']).issubset(nodes)):
            raise ValueError('来源处置状态或规范考点引用不合法')
        if (item['disposition'] == 'mapped') != bool(item['node_ids']):
            raise ValueError('只有已映射来源可以关联规范节点，已映射必须给出节点')
        _text(item['reason'], '来源处置依据')
        resolutions[key] = item
    for node in nodes.values():
        for ref in node['source_refs']:
            item = resolutions.get((ref['source_version_id'], ref['source_id']))
            if not item or item['disposition'] != 'mapped' or node['id'] not in item['node_ids']:
                raise ValueError('节点来源与来源处置映射不一致，不能把待核来源伪装为已核关联')
    if not isinstance(value['limitations'], list) or any(not isinstance(s, str) for s in value['limitations']):
        raise ValueError('目录限制须为文字数组')
    return value


def create_draft(conn, value, *, expected_parent):
    if active_id(conn) != expected_parent:
        raise ValueError('当前知识目录已变化，请重新读取后维护')
    validate(conn, value)
    sha = digest(value);rid = 'catalog-' + sha
    old = conn.execute('SELECT parent_id FROM knowledge_catalog_releases WHERE id=?', (rid,)).fetchone()
    if old:
        if active_id(conn) == rid:return document(conn, rid)
        if old[0] != expected_parent:raise ValueError('相同内容已属于其他父版本')
        return document(conn, rid)
    with atomic(conn):
        conn.execute('INSERT INTO knowledge_catalog_releases VALUES(?,?,?,?,?,?,NULL)',
                     (rid, expected_parent, 'draft', encode(value), sha, None))
        for node in value['nodes']:
            conn.execute('INSERT INTO knowledge_catalog_nodes VALUES(?,?,?,?,?,?)',
                         (rid, node['id'], node['parent_id'], node['name'], node['kind'], encode(node)))
        for link in value['redirects']:
            conn.execute('INSERT INTO knowledge_catalog_redirects VALUES(?,?,?,?)',
                         (rid, link['old_id'], link['target_id'], link['reason']))
    return document(conn, rid)


def publish(conn, release_id, *, expected_parent, reviewer):
    _text(reviewer, '目录维护者', 200)
    release = document(conn, release_id)
    if active_id(conn) == release_id and release['state'] == 'published':return release
    if active_id(conn) != expected_parent or release['parent_id'] != expected_parent:
        raise ValueError('目录发布父版本已变化，不能覆盖其他维护结果')
    validate(conn, release['document'])
    from app.common import now_iso
    with atomic(conn):
        conn.execute("UPDATE knowledge_catalog_releases SET state='published',reviewer=?,published_at=? WHERE id=?",
                     (reviewer, now_iso(), release_id))
        conn.execute('INSERT INTO knowledge_catalog_state VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET release_id=excluded.release_id', (release_id,))
    return document(conn, release_id)


def resolve(conn, node_id, release_id=None):
    release_id = release_id or active_id(conn)
    if not release_id:return None
    if conn.execute('SELECT 1 FROM knowledge_catalog_nodes WHERE release_id=? AND id=?', (release_id, node_id)).fetchone():return node_id
    row = conn.execute('SELECT target_id FROM knowledge_catalog_redirects WHERE release_id=? AND old_id=?', (release_id, node_id)).fetchone()
    return row[0] if row else None


def search(conn, *, query='', parent_id=None, kinds=None, release_id=None, offset=0, limit=40):
    release = document(conn, release_id)
    if not release:return {'release_id': None, 'total': 0, 'items': []}
    if not 1 <= limit <= 100 or offset < 0:raise ValueError('目录查询分页不合法')
    if kinds and not set(kinds).issubset(NODE_KINDS):raise ValueError('知识节点类型不合法')
    nodes = release['document']['nodes'];lookup = {n['id']: n for n in nodes}
    redirects = {link['old_id']: link['target_id'] for link in release['document']['redirects']}
    if parent_id and parent_id not in lookup:parent_id = redirects.get(parent_id, parent_id)
    if parent_id and parent_id not in lookup:raise ValueError('知识父节点不存在')
    if not isinstance(query,str) or len(query)>2000:raise ValueError('目录query须为不超过2000字的文本')
    # A directory lookup often spans several different concepts. Treat
    # explicitly separated terms as a union, not one concatenated phrase.
    parts=[part for part in re.split(r'[\s|、；;]+',query) if normalized(part)]
    terms=list(dict.fromkeys(normalized(part) for part in parts))
    if len(terms)>20:raise ValueError('每次目录查询最多20个关键词，请缩小范围或分次查询')
    # Resolve historical IDs in this captured release. Preserve punctuation:
    # IDs such as old.a-b and old.ab may refer to different concepts.
    supplied_ids={part.casefold() for part in parts}
    resolved_ids={target for old,target in redirects.items() if old.casefold() in supplied_ids}
    def matches(node):
        parent = node['parent_id'];inside = not parent_id or node['id'] == parent_id
        while parent and not inside:
            inside = parent == parent_id;parent = lookup[parent]['parent_id']
        return inside and (not kinds or node['kind'] in kinds) and (not terms or node['id'] in resolved_ids or any(
            term in normalized(text) for term in terms for text in [node['id'], node['name'], node['definition'], *node['aliases']]))
    matched = sorted((n for n in nodes if matches(n)), key=lambda n: n['id'])
    return {'release_id': release['id'], 'state': release['state'], 'total': len(matched),
            'items': matched[offset:offset + limit], 'offset': offset, 'limit': limit,
            'query_terms':terms,'match_mode':'any_term' if terms else 'all_nodes',
            'resolved_query_ids':sorted(resolved_ids),
            'search_policy':'空格或|/、/分号分隔的关键词取并集；已合并旧ID按本次目录版本解析到规范ID。单个词按规范文字匹配，不做数学适配判断。无命中时用更短词或上级目录浏览，不能据此断定目录没有该概念。'}


def navigation_result(result):
    """Tool search is navigation; actual definitions have their own read receipt.

    Preserve search membership, ordering and paging. Do not truncate candidates
    again, rank them by guessed relevance, or mutate the stored catalogue.
    Public catalogue APIs retain their full-document response.
    """
    fields=('id','name','kind','parent_id','aliases','math_types')
    return {**result,'items':[{key:node[key] for key in fields if key in node}
                              for node in result['items']],
            'projection':'navigation',
            'reading':'查询仅返回完整ID、名称、别名与范围；不登记定义阅读。用topic_ids原样传回完整ID读取定义/条件/边界。检查total与分页，不用自写关键词正则丢弃尚未阅读的候选。'}
