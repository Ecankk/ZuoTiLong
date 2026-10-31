"""Explicitly trusted catalogue snapshots, not synthetic Agent executions.

Packages contain a public projection of definitions and immutable source
anchors. They exclude original source bodies, maintenance notes and learners.
"""
import copy
import json
import re
import sqlite3
from urllib.parse import urlsplit, urlunsplit

from app.knowledge import catalog, outline
from app.storage import catalog_packages as store

FORMAT = 'mathlens.knowledge-package/v1'
HEX = re.compile(r'^[0-9a-f]{64}$')
REVIEW_NOTE = '通用目录已发布快照；导入出处单独保存，不代表本机重新完成来源审校。'
LIMITATIONS = ['固定来源的发布快照不认证当年官方考纲完整性或普遍数学正确率。',
               '仅包含通用知识和来源散列，不包含个人学习记录、原始来源正文或题库内容。']
PRIVATE = re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?:Users|home)/|codex://|codex-clipboard-|'
                     r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I)


def _hash(value):
    return catalog.digest({k: v for k, v in value.items() if k != 'sha256'})


def _references(source, metadata):
    if source == '11408Advance-mcp:mathematics':
        return [{'id': 'upstream-repository', 'title': '11408Advance-mcp',
                 'url': 'https://github.com/hanserdesu/11408Advance-mcp',
                 'locator': '固定revision对应的数学来源', 'sha256': None}]
    refs = []
    for row in metadata.get('references', []):
        parsed = urlsplit(row['url'])
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or getattr(parsed, 'pass' + 'word'):
            raise ValueError('公开来源URL不合法')
        # Queries/fragments are unnecessary for identifying the public source
        # and must not carry private retrieval tokens into a shared package.
        refs.append({k: row[k] for k in ('id', 'title', 'locator', 'sha256')} |
                    {'url': urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))})
    return refs


def export_package(conn):
    release = catalog.document(conn)
    if not release or release['state'] != 'published':
        raise ValueError('请先发布统一目录；草稿不能导出为共享目录')
    if store.exists(conn):
        for row in conn.execute('SELECT payload_json FROM knowledge_catalog_packages WHERE document_sha256=? ORDER BY rowid',
                                (release['content_sha256'],)):
            original = json.loads(row['payload_json'])
            if original['document'] == release['document']:
                validate_package(original)
                return original
    document = copy.deepcopy(release['document'])
    document['label'] = 'ZuoTiLong 通用考点目录'
    document['limitations'] = list(LIMITATIONS)
    for node in document['nodes']:
        node['review_note'] = REVIEW_NOTE
    for redirect in document['redirects']:
        redirect['reason'] = '已发布目录中的规范ID合并，旧ID保留。'
    for resolution in document['source_resolutions']:
        resolution['reason'] = ('已发布快照中的来源映射；不作为本机已读原文回执。'
                                if resolution['disposition'] == 'mapped' else
                                '沿用来源处置状态；待核/方法/导航不转为新的原子结论。')
    required = {}
    for item in document['source_resolutions']:
        required.setdefault(item['source_version_id'], set()).add(item['source_id'])
    for node in document['nodes']:
        for ref in node['source_refs']:
            required.setdefault(ref['source_version_id'], set()).add(ref['source_id'])
    sources = []
    for version, ids in sorted(required.items()):
        original = conn.execute('SELECT * FROM knowledge_source_versions WHERE id=?', (version,)).fetchone()
        if original:
            origin = dict(original)
            references = _references(origin['source'], json.loads(origin['metadata_json']))
        else:
            origin = store.source_metadata(conn, version)
            if not origin:
                raise ValueError('目录来源出处缺失，不能导出')
            references = origin['references']
        entries = []
        for rid in sorted(ids):
            if not store.source_known(conn, version, rid):
                raise ValueError('目录引用的来源条目不存在')
            row = conn.execute('SELECT * FROM knowledge_source_entries WHERE source_version_id=? AND id=?',
                               (version, rid)).fetchone()
            if row:
                value = json.loads(row['payload_json'])
                entry = {'id': rid, 'kind': row['kind'], 'content_sha256': row['content_sha256'],
                         'chapter_key': value.get('chapter_key', 'supplement')}
            else:
                entry = store.entry_metadata(conn, version, rid)
            if not entry:
                raise ValueError('目录引用的来源条目缺失，不能导出')
            entries.append(entry)
        sources.append({'id': version, 'source': origin['source'], 'revision': origin['revision'],
                        'manifest_sha256': origin['manifest_sha256'], 'references': references, 'entries': entries})
    package = {'schema_version': FORMAT,
               'origin': {'catalog_revision': release['id'], 'content_sha256': release['content_sha256']},
               'document': document, 'document_sha256': catalog.digest(document), 'sources': sources}
    package['sha256'] = _hash(package)
    validate_package(package)
    return package


def validate_package(package):
    fields = {'schema_version', 'origin', 'document', 'document_sha256', 'sources', 'sha256'}
    if not isinstance(package, dict) or set(package) != fields or package['schema_version'] != FORMAT:
        raise ValueError('共享目录包字段或版本不合法')
    if len(catalog.encode(package).encode()) > 16*1024*1024:
        raise ValueError('共享目录包过大')
    if not isinstance(package['sha256'], str) or not HEX.fullmatch(package['sha256']) or _hash(package) != package['sha256']:
        raise ValueError('共享目录包散列不匹配')
    origin = package['origin']
    if (not isinstance(origin, dict) or set(origin) != {'catalog_revision', 'content_sha256'}
            or not isinstance(origin['content_sha256'], str) or not HEX.fullmatch(origin['content_sha256'])
            or origin['catalog_revision'] != 'catalog-'+origin['content_sha256']):
        raise ValueError('共享目录来源版本不合法')
    if catalog.digest(package['document']) != package['document_sha256']:
        raise ValueError('共享目录定义散列不匹配')
    document = package['document']
    if not isinstance(document, dict) or document.get('label') != 'ZuoTiLong 通用考点目录' or document.get('limitations') != LIMITATIONS:
        raise ValueError('只接受明确标识的通用目录投影')
    if not isinstance(document.get('nodes'), list) or not 1 <= len(document['nodes']) <= 20000:
        raise ValueError('共享目录节点数量不合法')
    if any(not isinstance(n, dict) or n.get('review_note') != REVIEW_NOTE for n in document['nodes']):
        raise ValueError('共享目录不能携带私有维护备注')
    if PRIVATE.search(catalog.encode(package)):
        raise ValueError('共享目录包含本机路径或会话标识，请先核对通用字段')
    sources = package['sources']
    if not isinstance(sources, list) or len(sources) > 1000:
        raise ValueError('共享目录来源数量不合法')
    seen, total = set(), 0
    for source in sources:
        if not isinstance(source, dict) or set(source) != {'id', 'source', 'revision', 'manifest_sha256', 'references', 'entries'}:
            raise ValueError('共享来源字段不合法')
        if (not all(isinstance(source[k], str) and source[k] for k in ('id', 'source', 'revision', 'manifest_sha256'))
                or not catalog.ID.fullmatch(source['source']) or len(source['revision']) > 200
                or not HEX.fullmatch(source['manifest_sha256'])
                or source['id'] != 'source-'+catalog.digest({'source': source['source'], 'revision': source['revision']})
                or source['id'] in seen):
            raise ValueError('共享来源版本或身份不合法')
        seen.add(source['id'])
        if not isinstance(source['references'], list) or len(source['references']) > 100:
            raise ValueError('共享来源引用不合法')
        for reference in source['references']:
            if not isinstance(reference, dict) or set(reference) != {'id', 'title', 'url', 'locator', 'sha256'}:
                raise ValueError('公开来源引用字段不合法')
            if any(not isinstance(reference[k], str) or not reference[k] or len(reference[k]) > 4000 for k in ('id', 'title', 'url', 'locator')):
                raise ValueError('公开来源引用文字不合法')
            parsed = urlsplit(reference['url'])
            if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or getattr(parsed, 'pass' + 'word') or parsed.query or parsed.fragment:
                raise ValueError('公开来源引用不能携带凭据或查询参数')
            if reference['sha256'] is not None and (not isinstance(reference['sha256'], str) or not HEX.fullmatch(reference['sha256'])):
                raise ValueError('公开来源原文散列不合法')
        if not isinstance(source['entries'], list) or not source['entries']:
            raise ValueError('共享来源缺少条目出处')
        ids = set()
        for entry in source['entries']:
            if (not isinstance(entry, dict) or set(entry) != {'id', 'kind', 'content_sha256', 'chapter_key'}
                    or not isinstance(entry['id'], str) or not catalog.ID.fullmatch(entry['id']) or entry['id'] in ids
                    or entry['kind'] not in ('atom', 'combination')
                    or not isinstance(entry['content_sha256'], str) or not HEX.fullmatch(entry['content_sha256'])
                    or not isinstance(entry['chapter_key'], str) or not catalog.ID.fullmatch(entry['chapter_key'])):
                raise ValueError('共享来源条目不合法或重复')
            ids.add(entry['id']);total += 1
        if total > 50000:
            raise ValueError('共享来源条目过多')
    # Validate the real tree/source contract in an isolated catalogue-only DB.
    # Imported anchors are explicit provenance, never fabricated raw candidates.
    with sqlite3.connect(':memory:') as scratch:
        scratch.row_factory = sqlite3.Row
        catalog.initialize(scratch)
        scratch.execute('CREATE TABLE knowledge_nodes(id TEXT PRIMARY KEY)')
        scratch.executemany('INSERT INTO knowledge_nodes VALUES(?)', [(n[0],) for n in outline.seeds()])
        store.save(scratch, package, catalog.encode)
        catalog.validate(scratch, document)
    return {'sha256': package['sha256'], 'nodes': len(document['nodes']),
            'atoms': sum(n['kind'] == 'atom' for n in document['nodes']),
            'sources': len(sources), 'source_entries': total,
            'origin_catalog_revision': origin['catalog_revision'],
            'mathematical_review': 'published_snapshot_not_reverified_here',
            'original_source_text': 'not_included'}


def import_package(conn, package, *, trusted_sha256, expected_parent, confirmed):
    preview = validate_package(package)
    if confirmed is not True or trusted_sha256 != package['sha256']:
        raise ValueError('请明确接受目录包来源并核对其可信散列；格式校验不等于数学审校')
    rid = 'catalog-'+package['document_sha256']
    active = catalog.active_id(conn)
    if active == rid and conn.execute('SELECT 1 FROM knowledge_catalog_packages WHERE sha256=?', (package['sha256'],)).fetchone():
        return {'release_id': rid, 'sha256': package['sha256'], 'reused': True}
    with catalog.atomic(conn):
        if catalog.active_id(conn) != expected_parent:
            raise ValueError('当前目录已变化，请重新预览后导入')
        store.save(conn, package, catalog.encode)
        draft = catalog.create_draft(conn, package['document'], expected_parent=expected_parent)
        release = catalog.publish(conn, draft['id'], expected_parent=expected_parent,
                                  reviewer='imported-package:'+package['sha256'])
        store.record_activation(conn, package['sha256'], expected_parent, release['id'], 'import')
    return {**preview, 'release_id': rid, 'reused': False}


def activate_package(conn, sha256, *, expected_current, confirmed):
    if confirmed is not True:
        raise ValueError('切换共享目录版本需要明确确认')
    row = conn.execute('SELECT payload_json FROM knowledge_catalog_packages WHERE sha256=?', (sha256,)).fetchone()
    if not row:
        raise ValueError('该目录包尚未导入，不能切换')
    package = json.loads(row[0]);validate_package(package)
    target = 'catalog-'+package['document_sha256']
    release = catalog.document(conn, target)
    if not release or release['state'] != 'published' or release['document'] != package['document']:
        raise ValueError('已导入目录快照不完整，不能切换')
    current = catalog.active_id(conn)
    if current == target:
        return {'release_id': target, 'sha256': sha256, 'reused': True}
    with catalog.atomic(conn):
        if catalog.active_id(conn) != expected_current:
            raise ValueError('当前目录已变化，请重新核对切换目标')
        # Explicit historical activation preserves both immutable releases. It
        # does not rewrite a source, mapping, question, attempt or old receipt.
        conn.execute('UPDATE knowledge_catalog_state SET release_id=? WHERE singleton=1', (target,))
        store.record_activation(conn, sha256, current, target, 'activate_snapshot')
    return {'release_id': target, 'sha256': sha256, 'reused': False}
