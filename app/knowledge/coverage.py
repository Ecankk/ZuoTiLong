"""Read-only coverage accounting, separate from mathematical or learner assessment.

Counts describe the captured catalogue/source/material state. A chapter having
descendants is not evidence that its syllabus has been fully covered.
"""
from collections import Counter, defaultdict
from app.knowledge import catalog, outline


def build_report(release, sources, entries, ready_questions, *, outline_nodes=None,
                 annotation_counts=None):
    """Build metadata-only matrices; input collections contain no learner data."""
    document = release['document']
    nodes = {n['id']: n for n in document['nodes']}
    if len(nodes) != len(document['nodes']):
        raise ValueError('目录存在重复节点ID，不能生成覆盖报告')
    redirects = {r['old_id']: r['target_id'] for r in document.get('redirects', [])}

    def resolve(tid):
        seen = set()
        while tid in redirects:
            if tid in seen:
                raise ValueError('目录重定向成环')
            seen.add(tid)
            tid = redirects[tid]
        if tid not in nodes:
            raise ValueError('目录引用了不存在的节点')
        return tid

    paths = {}
    for tid in nodes:
        path, seen, current = [], set(), tid
        while current is not None:
            if current in seen or current not in nodes:
                raise ValueError('知识树父节点缺失或成环')
            seen.add(current)
            path.append(current)
            current = nodes[current]['parent_id']
        paths[tid] = path
    for tid in redirects:
        resolve(tid)

    resolutions = {}
    for item in document['source_resolutions']:
        key = (item['source_version_id'], item['source_id'])
        if key in resolutions:
            raise ValueError('同版来源被重复处置')
        resolutions[key] = item

    def bucket():
        return {'counts': Counter(), 'atoms': set(), 'pending': []}

    source_data = {s['id']: bucket() for s in sources}
    chapters = defaultdict(bucket)
    for entry in entries:
        sid, rid = entry['source_version_id'], entry['id']
        if sid not in source_data:
            raise ValueError('来源条目缺少固定版本')
        if entry['kind'] != 'atom':
            continue
        chapter = entry['chapter_key']
        item = resolutions.get((sid, rid))
        state = item['disposition'] if item else 'unresolved'
        atom_ids = {resolve(tid) for tid in item['node_ids']} if item else set()
        atom_ids = {tid for tid in atom_ids if nodes[tid]['kind'] == 'atom'}
        for target in (source_data[sid], chapters[(sid, chapter)]):
            target['counts'][state] += 1
            target['atoms'].update(atom_ids)
            if state in ('pending', 'unresolved'):
                target['pending'].append({'source_id': rid, 'status': state,
                                          'reason': item['reason'] if item else '尚无来源处置'})

    by_atom = defaultdict(lambda: {'records': set(), 'entities': set()})
    ready_records, ready_entities = set(), set()
    for question in ready_questions:
        bank_id, entity = question['bank_id'], question['entity_id']
        ready_records.add(bank_id)
        ready_entities.add(entity)
        for tid in question['topic_ids']:
            tid = resolve(tid)
            if nodes[tid]['kind'] != 'atom':
                continue
            by_atom[tid]['records'].add(bank_id)
            by_atom[tid]['entities'].add(entity)

    atom_rows = []
    for tid, node in sorted(nodes.items()):
        if node['kind'] != 'atom':
            continue
        coverage = by_atom[tid]
        atom_rows.append({'id': tid, 'name': node['name'], 'parent_id': node['parent_id'],
                          'ancestor_ids': paths[tid][1:],
                          'ready_source_records': len(coverage['records']),
                          'ready_question_entities': len(coverage['entities'])})

    outline_rows = []
    for tid, parent, name in outline_nodes if outline_nodes is not None else outline.seeds():
        if parent is None:
            continue
        descendants = {row['id'] for row in atom_rows if tid in paths[row['id']]}
        records, entities = set(), set()
        for aid in descendants:
            records.update(by_atom[aid]['records'])
            entities.update(by_atom[aid]['entities'])
        outline_rows.append({'id': tid, 'name': name, 'present': tid in nodes,
                             'published_atoms': len(descendants),
                             'ready_source_records': len(records),
                             'ready_question_entities': len(entities),
                             'scope_review': 'not_proven_by_counts'})

    def totals(value):
        return {'source_atoms': sum(value['counts'].values()),
                'dispositions': dict(sorted(value['counts'].items())),
                'mapped_published_atoms': len(value['atoms']),
                'pending': sorted(value['pending'], key=lambda p: p['source_id'])}

    source_rows = []
    chapter_rows = []
    for source in sorted(sources, key=lambda s: s['id']):
        sid = source['id']
        source_rows.append({'source_version_id': sid, 'source': source['source'],
                            'revision': source['revision'],
                            'provenance': source.get('provenance', 'local_source_entries'),
                            **totals(source_data[sid])})
        for (version, key), value in sorted(chapters.items()):
            if version != sid:
                continue
            chapter_rows.append({'source_version_id': sid, 'chapter_key': key,
                                 'name': source.get('chapters', {}).get(key, key), **totals(value)})
    return {'schema_version': 'mathlens.knowledge-coverage/v1',
            'catalog_revision': release['id'],
            'catalog_sha256': release['content_sha256'],
            'outline_reference': outline.REFERENCE,
            'claims': {'official_syllabus_complete': 'not_evaluated',
                       'mathematical_accuracy_complete': 'not_evaluated',
                       'learner_mastery': 'not_evaluated'},
            'summary': {'published_nodes': len(nodes), 'published_atoms': len(atom_rows),
                        'atoms_with_ready_questions': sum(r['ready_source_records'] > 0 for r in atom_rows),
                        'ready_source_records': len(ready_records),
                        'ready_question_entities': len(ready_entities),
                        'annotation_states': annotation_counts or {}},
            'sources': source_rows, 'source_chapters': chapter_rows,
            'outline': outline_rows, 'atoms': atom_rows}


def read_report(conn, data):
    """Read within the caller's snapshot; never initialize or modify tables."""
    import json
    from app.bank.annotations import current
    release = catalog.document(conn)
    if not release:
        raise ValueError('尚未发布统一目录，不能生成覆盖报告')
    sources = []
    for row in conn.execute('SELECT * FROM knowledge_source_versions ORDER BY id'):
        metadata = json.loads(row['metadata_json'])
        sources.append({'id': row['id'], 'source': row['source'], 'revision': row['revision'],
                        'chapters': {ch['key']: ch.get('title', ch['key'])
                                     for ch in metadata.get('chapters', [])}})
    entries = []
    for row in conn.execute('SELECT * FROM knowledge_source_entries ORDER BY source_version_id,id'):
        payload = json.loads(row['payload_json'])
        entries.append({'source_version_id': row['source_version_id'], 'id': row['id'],
                        'kind': row['kind'], 'chapter_key': payload.get('chapter_key', 'supplement')})
    # Shared packages provide explicit metadata anchors, not raw source text.
    from app.storage.catalog_packages import all_sources, all_entries
    known_sources = {s['id'] for s in sources}
    for source in all_sources(conn):
        if source['id'] not in known_sources:
            sources.append({'id': source['id'], 'source': source['source'], 'revision': source['revision'],
                            'chapters': {}, 'provenance': 'imported_catalogue_only'})
    known_entries = {(e['source_version_id'], e['id']) for e in entries}
    for entry in all_entries(conn):
        if (entry['source_version_id'], entry['id']) not in known_entries:
            entries.append(entry)
    linked = {r[0] for r in conn.execute('SELECT DISTINCT bank_id FROM question_annotation_links')}
    from app.storage.annotation_cache import exists as cache_exists
    if cache_exists(conn):
        linked.update(r[0] for r in conn.execute('SELECT DISTINCT bank_id FROM imported_question_annotations'))
    states, ready = Counter(), []
    for row in conn.execute("SELECT id FROM bank_questions WHERE source!='本地示例题库' ORDER BY id"):
        bid = row['id']
        if bid not in linked:
            states['not_annotated'] += 1
            continue
        try:
            annotation = current(conn, data, bid)
        except ValueError:
            annotation = None
        if not annotation:
            states['no_current_annotation'] += 1
            continue
        state = annotation['analysis']['status']
        states[state] += 1
        if state == 'ready':
            ready.append({'bank_id': bid, 'entity_id': annotation['entity_id'],
                          'topic_ids': [b['topic_id'] for b in annotation['analysis']['bindings']]})
    return build_report(release, sources, entries, ready, annotation_counts=dict(states))


def markdown(report):
    """A short navigation report; detailed node metadata lives in the JSON."""
    summary = report['summary']
    lines = ['# 统一目录与可用题覆盖核对', '',
             f"目录版本：`{report['catalog_revision']}`。",
             '只统计固定来源处置、项目粗目录和当前有效题目标注；不认证官方考纲完整性、数学准确率或学生掌握度。', '',
             f"发布节点 {summary['published_nodes']}，其中原子 {summary['published_atoms']}；"
             f"{summary['atoms_with_ready_questions']} 个原子已有当前就绪题。",
             f"就绪题源记录 {summary['ready_source_records']}，确认题目实体 {summary['ready_question_entities']}。"
             '同题跨类记录与独立题目分开统计，不将未就绪等同于资料无题。', '',
             '## 项目粗目录', '',
             '| 章节 | 发布原子 | 就绪来源记录 | 确认题目实体 |',
             '| --- | ---: | ---: | ---: |']
    for row in report['outline']:
        name = row['name'].replace('|', '／')
        lines.append(f"| {name} | {row['published_atoms']} | {row['ready_source_records']} | {row['ready_question_entities']} |")
    lines += ['', '有后代节点或练习不等于整章覆盖；无练习不等于学生薄弱。', '',
              '## 固定来源章节处置', '',
              '| 来源版本 | 章节 | 来源原子 | 映射 | 方法 | 导航/排除 | 待核/未处置 |',
              '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for row in report['source_chapters']:
        state = row['dispositions']
        lines.append(f"| {row['source_version_id']} | {row['name'].replace('|', '／')} | {row['source_atoms']} | "
                     f"{state.get('mapped', 0)} | {state.get('method', 0)} | "
                     f"{state.get('navigation', 0)+state.get('excluded', 0)} | "
                     f"{state.get('pending', 0)+state.get('unresolved', 0)} |")
    lines += ['', '方法与导航另有合理处置，不为了凑原子数量重新建点。待核条目与逐原子就绪数量见同名JSON。', '']
    return '\n'.join(lines)
