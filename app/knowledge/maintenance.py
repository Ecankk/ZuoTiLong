"""Explicit catalogue-maintenance tasks, separate from student diagnostics."""
import json
from app.knowledge import catalog

KINDS = ('maintain_catalog', 'annotate_questions')


def normalize_scope(kind, scope):
    if kind == 'annotate_questions':
        if (not isinstance(scope, dict) or 'bank_ids' not in scope
                or not set(scope).issubset({'bank_ids', 'review_note', 'revision'})):
            raise ValueError('通用题目任务须明确bank_ids')
        ids = scope['bank_ids']
        if not isinstance(ids, list) or not 1 <= len(ids) <= 8 or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
            raise ValueError('题目标注每批须为1–8个不同ID')
        result = {'bank_ids': sorted(ids)}
        if 'revision' in scope:
            from app.bank.annotation_revisions import normalize
            result['revision'] = normalize(scope['revision'], ids)
        if 'review_note' in scope:
            note = scope['review_note']
            if not isinstance(note, str) or not 1 <= len(note.strip()) <= 4000:
                raise ValueError('题目标注复核说明须为1–4000字的具体问题和依据')
            result['review_note'] = note.strip()
        return result
    if kind == 'maintain_catalog':
        required = {'source_version_id', 'source_ids'}
        if not isinstance(scope, dict) or not required.issubset(scope) or not set(scope).issubset(required | {'review_note','reference_ids'}):
            raise ValueError('目录维护须明确固定来源版本与条目ID')
        version, ids = scope['source_version_id'], scope['source_ids']
        if not isinstance(version, str) or not catalog.ID.fullmatch(version):
            raise ValueError('目录维护来源版本不合法')
        if not isinstance(ids, list) or not 1 <= len(ids) <= 40 or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
            raise ValueError('目录维护每批须为1–40个不同来源条目')
        result = {'source_version_id': version, 'source_ids': sorted(ids)}
        if 'reference_ids' in scope:
            refs=scope['reference_ids']
            if not isinstance(refs,list) or not 1<=len(refs)<=50 or any(not isinstance(r,str) or not catalog.ID.fullmatch(r) for r in refs) or len(set(refs))!=len(refs):
                raise ValueError('须明确1–50个不同来源依据ID')
            result['reference_ids']=sorted(refs)
        if 'review_note' in scope:
            note = scope['review_note']
            if not isinstance(note, str) or not 1 <= len(note.strip()) <= 4000:
                raise ValueError('目录复核说明须为1–4000字的具体问题和依据')
            result['review_note'] = note.strip()
        return result
    raise ValueError('不是目录或题库准备任务')


def capture(conn, data, kind, scope, *, annotation_rule_revision=None):
    scope = normalize_scope(kind, scope)
    if kind == 'annotate_questions':
        from app.bank.annotations import capture as capture_questions
        return capture_questions(conn, data, scope,rule_revision=annotation_rule_revision)
    entries = []
    for sid in scope['source_ids']:
        row = conn.execute('SELECT * FROM knowledge_source_entries WHERE source_version_id=? AND id=?',
                           (scope['source_version_id'], sid)).fetchone()
        if not row or row['kind'] != 'atom':raise ValueError('目录维护来源条目不存在或不是原子候选')
        entries.append({'source_id': sid, 'content_sha256': row['content_sha256'],
                        'content': json.loads(row['payload_json'])})
    value={'task_scope': scope, 'catalog_revision': catalog.active_id(conn),
           'catalog_base': catalog.base_document(conn), 'source_entries': entries,
           'rule_revision': 'mathlens.catalog-maintenance/v1'}
    if scope.get('reference_ids'):
        from app.knowledge.references import material
        for rid in scope['reference_ids']:material(data,value,rid)
    return value


def source_context(inputs, source_ids):
    """Locate prior associations in the captured catalogue without marking definitions read."""
    version = inputs['task_scope']['source_version_id']
    requested = set(source_ids)
    resolutions = [{key: value for key, value in row.items() if key != 'source_version_id'}
                   for row in inputs['catalog_base']['source_resolutions']
                   if row['source_version_id'] == version and row['source_id'] in requested]
    related = {nid for row in resolutions for nid in row['node_ids']}
    entries = {entry['source_id']: entry for entry in inputs['source_entries']}
    return {'source_entries': [entries[sid] for sid in source_ids],
            'source_version_id': version, 'catalog_revision': inputs['catalog_revision'],
            'existing_source_resolutions': resolutions,
            'related_nodes': [{key: node[key] for key in ('id', 'name', 'kind')}
                              for node in inputs['catalog_base']['nodes'] if node['id'] in related],
            'reading': '已有来源处置用于保留完整关联；节点摘要不算读取定义，复用或修改前仍用topic_ids读取。'}


def guard(conn, data, kind, scope):
    # The task itself captures the catalogue at dispatch. Waiting batches may
    # follow earlier catalogue releases without being made stale in advance.
    inputs = capture(conn, data, kind, scope)
    if kind == 'maintain_catalog':
        return {'task_scope': inputs['task_scope'],
                'source_revisions': [[e['source_id'], e['content_sha256']] for e in inputs['source_entries']]}
    value = {'task_scope': inputs['task_scope'], 'materials': [
        [q['bank_id'], q['material_revision'], q['identity']] for q in inputs['bank_questions']]}
    if 'revision' in inputs['task_scope']:
        value['revision_bases'] = [[q['bank_id'], q['revision_base']['annotation_id'],
                                   catalog.digest(q['revision_base']['analysis'])] for q in inputs['bank_questions']]
    return value


def save(conn, task, inputs, result):
    from app.learning.tasks import require_read
    scope = inputs['task_scope'];version = scope['source_version_id']
    supplied = result['source_resolutions']
    if len({r['source_id'] for r in supplied}) != len(supplied) or {r['source_id'] for r in supplied} != set(scope['source_ids']):
        raise ValueError('目录维护必须逐项处置本批来源，不得遗漏或新增来源')
    for entry in inputs['source_entries']:
        require_read(conn, task, 'knowledge_source', entry['source_id'], version, entry['content_sha256'])
    # Old captured scopes have no reference_ids and keep their original gate.
    if scope.get('reference_ids'):
        from app.knowledge.references import reference_specs
        refs=reference_specs(inputs)
        for rid in scope['reference_ids']:
            require_read(conn,task,'knowledge_reference',rid,version,refs[rid]['sha256'])
    value = json.loads(catalog.encode(inputs['catalog_base']))
    known = {n['id']: n for n in value['nodes']}
    changes = result['node_changes']
    if len({n['id'] for n in changes}) != len(changes):raise ValueError('维护结果重复更新同一考点')
    allowed = {(version, source_id) for source_id in scope['source_ids']}
    for node in changes:
        if node['id'] in known:
            require_read(conn, task, 'knowledge_definition', node['id'], inputs['catalog_revision'] or 'outline', catalog.digest(known[node['id']]))
        if node['kind'] == 'atom' and not any((ref['source_version_id'], ref['source_id']) in allowed for ref in node['source_refs']):
            raise ValueError('新增/修改原子须有本批已读来源依据，不得借维护任务自由建点')
        known[node['id']] = node
    redirects = {link['old_id']: link for link in value['redirects']}
    for link in result['redirects']:
        if link['old_id'] not in known:raise ValueError('合并的旧考点不存在')
        require_read(conn, task, 'knowledge_definition', link['old_id'], inputs['catalog_revision'] or 'outline', catalog.digest(known[link['old_id']]))
        if link['target_id'] in {n['id'] for n in inputs['catalog_base']['nodes']}:
            original = next(n for n in inputs['catalog_base']['nodes'] if n['id'] == link['target_id'])
            require_read(conn, task, 'knowledge_definition', link['target_id'], inputs['catalog_revision'] or 'outline', catalog.digest(original))
        del known[link['old_id']];redirects[link['old_id']] = link
    # Preserve old aliases and source dispositions while flattening only
    # explicitly reviewed redirects to a current target.
    def target(nid):
        seen = set()
        while nid in redirects:
            if nid in seen:raise ValueError('目录合并形成循环')
            seen.add(nid);nid = redirects[nid]['target_id']
        return nid
    for node in known.values():
        if node['parent_id']:node['parent_id'] = target(node['parent_id'])
    for link in redirects.values():link['target_id'] = target(link['target_id'])
    resolutions = {(r['source_version_id'], r['source_id']): r for r in value['source_resolutions']}
    for row in supplied:
        row = {**row, 'source_version_id': version}
        for tid in row['node_ids']:
            if tid in {n['id'] for n in inputs['catalog_base']['nodes']} and tid not in {n['id'] for n in changes}:
                original = next(n for n in inputs['catalog_base']['nodes'] if n['id'] == tid)
                require_read(conn, task, 'knowledge_definition', tid, inputs['catalog_revision'] or 'outline', catalog.digest(original))
        resolutions[(version, row['source_id'])] = row
    for row in resolutions.values():row['node_ids'] = sorted({target(t) for t in row['node_ids']})
    value.update(label='统一考研数学知识目录', nodes=sorted(known.values(), key=lambda n: n['id']),
                 redirects=sorted(redirects.values(), key=lambda r: r['old_id']),
                 source_resolutions=sorted(resolutions.values(), key=lambda r: (r['source_version_id'], r['source_id'])),
                 limitations=result['limitations'])
    draft = catalog.create_draft(conn, value, expected_parent=inputs['catalog_revision'])
    released = catalog.publish(conn, draft['id'], expected_parent=inputs['catalog_revision'], reviewer='catalog-maintenance')
    return {'catalog_revision': released['id'], 'source_entries': len(supplied),
            'pending': sum(r['disposition'] == 'pending' for r in supplied)}
