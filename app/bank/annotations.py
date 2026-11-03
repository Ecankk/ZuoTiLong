"""Reusable, versioned mathematical analyses of bank questions.

This is shared question knowledge. It never creates student attempts, learning
events or mastery judgments. A valid analysis is reused only with matching
materials, confirmed identity evidence and unchanged concept definitions.
"""
import json
import hashlib
from pathlib import Path
import uuid
from app.knowledge import catalog
from app.bank.access import aliases
from app.storage.boundaries import material_path, library_root, table_exists

RULE_REVISION = 'mathlens.question-topics/v3'
SUPPORTED_RULE_REVISIONS = ('mathlens.question-topics/v1','mathlens.question-topics/v2',RULE_REVISION)
DEPENDENCY_FIELDS = ('kind','definition','conditions','boundaries','parent_id','math_types')
ROLES = ('primary', 'supporting', 'prerequisite')
STAGES = ('entry', 'modeling', 'formula', 'calculation', 'finalization', 'unknown')


def initialize(conn):
    for sql in (
        '''CREATE TABLE IF NOT EXISTS question_annotations(
        id TEXT PRIMARY KEY,bank_id TEXT NOT NULL REFERENCES bank_questions(id),entity_id TEXT NOT NULL,
        content_revision TEXT NOT NULL,material_revision TEXT NOT NULL,catalog_revision TEXT NOT NULL,
        rule_revision TEXT NOT NULL,dependencies_json TEXT NOT NULL,identity_json TEXT NOT NULL,
        result_id TEXT NOT NULL REFERENCES learning_results(id),payload_json TEXT NOT NULL,created_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS question_annotation_links(
        bank_id TEXT NOT NULL REFERENCES bank_questions(id),annotation_id TEXT NOT NULL REFERENCES question_annotations(id),
        question_revision TEXT NOT NULL,PRIMARY KEY(bank_id,annotation_id))''',
        '''CREATE TABLE IF NOT EXISTS question_annotation_topics(
        annotation_id TEXT NOT NULL REFERENCES question_annotations(id),topic_id TEXT NOT NULL,
        role TEXT NOT NULL,stages_json TEXT NOT NULL,PRIMARY KEY(annotation_id,topic_id))''',
        '''CREATE INDEX IF NOT EXISTS idx_annotation_bank ON question_annotation_links(bank_id)''',
        '''CREATE INDEX IF NOT EXISTS idx_annotation_topic ON question_annotation_topics(topic_id,role)''',
    ):
        conn.execute(sql)
    from app.storage.annotation_cache import initialize as initialize_shared_provenance
    initialize_shared_provenance(conn)


def materials(conn, data, bank_id):
    from app.learning.tasks import resource_digest
    row = conn.execute('SELECT * FROM bank_questions WHERE id=?', (bank_id,)).fetchone()
    if not row:raise ValueError('题库题目不存在')
    resource = conn.execute('SELECT * FROM bank_resources WHERE bank_id=?', (bank_id,)).fetchone()
    fields = {'question': 'stem', 'analysis': 'explanation', 'answer': 'answer'}
    result = {}
    for role, field in fields.items():
        text = row[field] or ''
        path = resource[role + '_path'] if resource else None
        sha = None
        if path:
            actual = material_path(data, path).resolve()
            if not actual.is_relative_to((library_root(data)/'bank-assets').resolve()):
                raise ValueError('题库准备材料路径越界')
            sha = resource_digest(actual, Path(data))
        if text or sha:
            result[role] = {'text': text, 'path': path, 'image_sha256': sha,
                            'sha256': catalog.digest({'text': text, 'image_sha256': sha})}
    if 'question' not in result:raise ValueError('题库缺少可阅读题干')
    return result


def question_revision(conn, data, bank_id):
    return materials(conn, data, bank_id)['question']['sha256']


def reference_signature(source):
    """Reference content, independent of source labels and filesystem paths."""
    return {role:source[role]['sha256'] for role in ('answer','analysis') if role in source}


def capture(conn, data, scope, *, rule_revision=None):
    from app.knowledge.maintenance import normalize_scope
    scope = normalize_scope('annotate_questions', scope)
    ids = scope['bank_ids']
    release = catalog.document(conn)
    if not release:raise ValueError('请先发布统一知识目录，再开始题目标注')
    rules=rule_revision or RULE_REVISION
    if rules not in SUPPORTED_RULE_REVISIONS:raise ValueError('题目分析规则版本不受支持')
    revision = scope.get('revision')
    bases = {}
    if revision:
        if rules != RULE_REVISION:raise ValueError('窄修订须使用当前题目标注规则')
        from app.bank.annotation_revisions import capture_bases
        bases = capture_bases(conn, data, ids, revision)
    entries = [];seen_identity = set()
    for bid in sorted(ids):
        if bid in seen_identity:continue
        source = materials(conn, data, bid)
        group=sorted(aliases(conn,bid))
        identity={}
        for other in group:
            other_materials=source if other==bid else materials(conn,data,other)
            if rules=='mathlens.question-topics/v1' or reference_signature(other_materials)==reference_signature(source):
                identity[other]=other_materials['question']['sha256']
        seen_identity.update(identity)
        entry={'bank_id': bid, 'content_revision': source['question']['sha256'],
                        'material_revision': catalog.digest(source), 'materials': source,
                        'identity': identity,
                        'entity_id': 'question-' + uuid.uuid5(uuid.NAMESPACE_URL, 'mathlens:bank:' + min(group)).hex}
        if revision:
            from app.bank.annotation_revisions import frozen_base
            entry['revision_base'] = frozen_base(bases[bid], entry, revision)
        if rules!='mathlens.question-topics/v1':
            for other in group:
                if other in identity:continue
                previous=current(conn,data,other)
                if previous and previous['analysis']['status']=='ready' and not previous.get('cache_provenance'):
                    entry['reusable_analysis']={'annotation_id':previous['id'],'source_bank_id':other,
                        'notice':'已确认同题的数学分析可复用；本题答案/解析版本尚未核对，不能继承其consistent或ready状态，仍须实际读本题全部材料。',
                        **{key:previous['analysis'][key] for key in ('reference_reasoning','bindings','methods','checkpoints','fingerprint')}}
                    break
        if rules=='mathlens.question-topics/v3' and 'reusable_analysis' not in entry:
            draft=definition_review_draft(conn,data,bid,source,release)
            if draft:entry['definition_review_draft']=draft
        entries.append(entry)
    return {'task_scope': scope, 'catalog_revision': release['id'],
            'rule_revision': rules, 'bank_questions': sorted(entries, key=lambda q: q['bank_id'])}


def analysis_context(inputs, bank_ids):
    """Expose captured mathematical drafts, without granting material reads."""
    available = {q['bank_id']: q for q in inputs['bank_questions']}
    if (not isinstance(bank_ids, list) or not 1 <= len(bank_ids) <= 8
            or any(not isinstance(bid, str) for bid in bank_ids)
            or len(set(bank_ids)) != len(bank_ids) or not set(bank_ids).issubset(available)):
        raise ValueError('每次读取本批题目清单中1–8个不同bank_id的固定分析上下文')
    fields = ('bank_id', 'content_revision', 'material_revision', 'entity_id',
              'revision_base', 'reusable_analysis', 'definition_review_draft')
    return {'catalog_revision': inputs['catalog_revision'], 'rule_revision': inputs['rule_revision'],
            'questions': [{key: available[bid][key] for key in fields if key in available[bid]} for bid in bank_ids],
            'reading': '旧分析是固定草稿或修订基线，不登记材料/定义阅读，不继承就绪判断；仍实际读取本题全部材料与所引用定义。'}


def concept_dependencies(conn, topic_ids, release_id=None, *, read_view=None):
    current = read_view.release if read_view is not None else catalog.document(conn, release_id)
    if not current:raise ValueError('没有已发布知识目录')
    nodes = read_view.nodes if read_view is not None else {n['id']: n for n in current['document']['nodes']}
    result = {}
    for supplied in topic_ids:
        tid = read_view.resolve(supplied) if read_view is not None else catalog.resolve(conn, supplied, current['id'])
        if not tid:raise ValueError('题目标注引用未知知识ID')
        while tid:
            node = nodes[tid]
            result[tid] = catalog.digest({key: node[key] for key in DEPENDENCY_FIELDS})
            tid = node['parent_id']
    return result


def save(conn, result_id, inputs, result, *, data):
    from app.learning.tasks import require_read
    from app.learning.loop import stamp
    available = {q['bank_id']: q for q in inputs['bank_questions']}
    questions = result['questions']
    if len({q['bank_id'] for q in questions}) != len(questions) or {q['bank_id'] for q in questions} != set(available):
        raise ValueError('题目标注必须覆盖本批全部题目，不能遗漏或夹带其他题')
    release = catalog.document(conn, inputs['catalog_revision'])
    nodes = {n['id']: n for n in release['document']['nodes']}
    task = conn.execute('SELECT * FROM learning_tasks WHERE id=(SELECT task_id FROM learning_results WHERE id=?)', (result_id,)).fetchone()
    saved = []
    for item in questions:
        source = available[item['bank_id']]
        from app.bank.annotation_revisions import validate, existing_binding_ids, introduces_binding_collision
        previous = current(conn, data, item['bank_id'])
        if (previous and previous['analysis']['status'] == 'needs_review' and item['status'] == 'ready'
                and not source.get('revision_base', {}).get('resolve_review')):
            raise ValueError('待核标注升级须使用明确的resolve_review修订基线和写入票据')
        validate(source, item)
        if (item['content_revision'], item['material_revision']) != (source['content_revision'], source['material_revision']):
            raise ValueError('标注题目或材料版本不匹配')
        for role, material in source['materials'].items():
            require_read(conn, task, 'bank_preparation', item['bank_id'], role, material['sha256'])
        bindings = item['bindings'];ids = [b['topic_id'] for b in bindings]
        preserved = existing_binding_ids(source)
        resolved = {tid: catalog.resolve(conn, tid, inputs['catalog_revision']) for tid in ids}
        if (len(set(ids)) != len(ids) or any(tid not in nodes and tid not in preserved for tid in ids)
                or any(value not in nodes for value in resolved.values())
                or introduces_binding_collision(source, ids, resolved)):
            raise ValueError('原子关联重复或含未知ID')
        for binding in bindings:
            tid = resolved[binding['topic_id']]
            if nodes[tid]['kind'] != 'atom':
                raise ValueError('题目须引用已发布原子；大考点由祖先推导，不能只贴粗章')
            require_read(conn, task, 'knowledge_definition', tid, inputs['catalog_revision'], catalog.digest(nodes[tid]))
        if item['status'] == 'ready':
            if not any(b['role'] == 'primary' for b in bindings) or item['unmatched_topics']:
                raise ValueError('就绪题须有主要原子且没有未解决的必要考点缺口')
            if item['answer_check']['status'] != 'consistent' or not any(role in source['materials'] for role in ('answer','analysis')):
                raise ValueError('参考内容缺失或有冲突时不能加入默认补强池')
        elif not item['limitations'] and not item['unmatched_topics']:
            raise ValueError('未就绪题须说明具体材料/数学/目录限制')
        aid = 'annotation-' + uuid.uuid5(uuid.NAMESPACE_URL, result_id + ':' + item['bank_id']).hex
        deps = concept_dependencies(conn, ids, inputs['catalog_revision'])
        conn.execute('INSERT INTO question_annotations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                     (aid, item['bank_id'], source['entity_id'], source['content_revision'], source['material_revision'],
                      inputs['catalog_revision'], inputs['rule_revision'], catalog.encode(deps), catalog.encode(source['identity']),
                      result_id, catalog.encode(item), stamp()))
        from app.storage.annotation_cache import register
        register(conn, aid)
        for bid, revision in source['identity'].items():
            conn.execute('INSERT INTO question_annotation_links VALUES(?,?,?)', (bid, aid, revision))
        for binding in bindings:
            conn.execute('INSERT INTO question_annotation_topics VALUES(?,?,?,?)',
                         (aid, binding['topic_id'], binding['role'], catalog.encode(binding['stages'])))
        saved.append(aid)
    if table_exists(conn, 'annotation_provenance'):
        from app.storage.provenance import save_provenance
        save_provenance(conn, task, inputs, result_id)
    return {'annotation_ids': saved, 'ready': sum(q['status'] == 'ready' for q in questions)}


def _unchanged_materials(conn,data,bank_id,row,source=None,*,read_view=None):
    """A historical proof cannot move to unreviewed references or a new question."""
    group=read_view.aliases(bank_id) if read_view is not None else aliases(conn,bank_id)
    read_materials=read_view.materials if read_view is not None else lambda bid:materials(conn,data,bid)
    if row['bank_id'] not in group:return False
    original=source if source is not None and row['bank_id']==bank_id else read_materials(row['bank_id'])
    if catalog.digest(original)!=row['material_revision']:return False
    if bank_id!=row['bank_id']:
        target=source if source is not None else read_materials(bank_id)
        if reference_signature(target)!=reference_signature(original):return False
    return bool(set(json.loads(row['identity_json'])).intersection(group))


def definition_review_draft(conn,data,bank_id,source,release):
    """Reuse an invalidated derivation only as a bounded, non-authoritative draft.

    v1/v2 task captures never call this function, so their immutable input hashes
    remain reproducible. All new material/definition reading gates still apply.
    """
    live={n['id']:n for n in release['document']['nodes']}
    confirmed_group=aliases(conn,bank_id)
    rows=conn.execute('''SELECT a.* FROM question_annotations a JOIN question_annotation_links l ON l.annotation_id=a.id
        WHERE l.bank_id=? AND l.question_revision=? ORDER BY a.rowid DESC''',(bank_id,source['question']['sha256']))
    for row in rows:
        if row['rule_revision'] not in SUPPORTED_RULE_REVISIONS:continue
        if row['bank_id'] not in confirmed_group:continue
        try:
            if not _unchanged_materials(conn,data,bank_id,row,source):continue
            previous=json.loads(row['payload_json'])
            # A newer unresolved mathematical assessment takes precedence over
            # any older ready derivation; do not cherry-pick earlier approval.
            if previous['status']!='ready':return None
            old_release=catalog.document(conn,row['catalog_revision'])
            old_nodes={n['id']:n for n in old_release['document']['nodes']}
            dependencies=json.loads(row['dependencies_json'])
            if not dependencies or any(tid not in old_nodes or catalog.digest({key:old_nodes[tid][key] for key in DEPENDENCY_FIELDS})!=digest
                                       for tid,digest in dependencies.items()):return None
            changes=[];resolved_ids=set()
            for tid,digest in dependencies.items():
                canonical=catalog.resolve(conn,tid,release['id'])
                node=live.get(canonical);resolved_ids.add(canonical)
                before=old_nodes[tid]
                after={key:node[key] for key in DEPENDENCY_FIELDS} if node else None
                if after is not None and catalog.digest(after)==digest:continue
                changes.append({'previous_id':tid,'current_id':canonical,
                    'previous':{key:before[key] for key in ('id','name',*DEPENDENCY_FIELDS)},
                    'current':{key:node[key] for key in ('id','name',*DEPENDENCY_FIELDS)} if node else None,
                    'changed_fields':[key for key in DEPENDENCY_FIELDS if node is None or before[key]!=node[key]]})
            # A changed parent can introduce additional prerequisites even when
            # that parent was not present in the original dependency closure.
            lineage=set()
            for canonical in resolved_ids:
                while canonical and canonical not in lineage:
                    lineage.add(canonical);canonical=live[canonical]['parent_id']
            for tid in sorted(lineage-resolved_ids):
                node=live[tid]
                changes.append({'previous_id':None,'current_id':tid,'previous':None,
                    'current':{key:node[key] for key in ('id','name',*DEPENDENCY_FIELDS)},
                    'changed_fields':list(DEPENDENCY_FIELDS)})
            if not changes:return None
            return {'annotation_id':row['id'],'source_bank_id':row['bank_id'],
                'source_catalog_revision':row['catalog_revision'],'review_catalog_revision':release['id'],
                'review_required':True,
                'notice':'同题及本版本参考材料未变，但相关知识定义或层级已变；以下仅为失效的历史推导草稿。须读当前材料和适用原子定义，逐步复核后重新交付，不能继承旧参考结论或ready状态。',
                'changed_knowledge':changes,
                **{key:previous[key] for key in ('reference_reasoning','bindings','methods','checkpoints','fingerprint')}}
        except ValueError:
            continue
    return None


def current(conn, data, bank_id, *, read_view=None):
    if read_view is not None and (read_view.conn is not conn or read_view.data!=data):
        raise ValueError('只读标注视图不属于当前事务或资料目录')
    if read_view is not None:read_view.validate()
    revision = read_view.materials(bank_id)['question']['sha256'] if read_view is not None else question_revision(conn, data, bank_id)
    from app.storage import annotation_cache as cache
    rows = list(conn.execute('''SELECT a.*,a.rowid AS local_order FROM question_annotations a JOIN question_annotation_links l ON l.annotation_id=a.id
        WHERE l.bank_id=? AND l.question_revision=? ORDER BY a.rowid DESC''', (bank_id, revision)))
    has_origins = cache.exists(conn)
    maximum = conn.execute('SELECT coalesce(max(rowid),0) FROM prepared_annotation_ids').fetchone()[0] if has_origins else 0
    choices = []
    for row in rows:
        order = conn.execute('SELECT rowid FROM prepared_annotation_ids WHERE id=?', (row['id'],)).fetchone() if has_origins else None
        choices.append((order[0] if order else maximum + row['local_order'], False, row))
    choices.extend((row['order_id'], True, row) for row in cache.candidates(conn, bank_id))
    for _, imported, row in sorted(choices, key=lambda item: item[0], reverse=True):
        if imported:
            from app.bank.annotation_packages import cache_current
            try:
                value = cache_current(conn, data, row, read_view=read_view)
            except (ValueError, KeyError, TypeError):
                value = None
            if value:
                return value
            continue
        item = json.loads(row['payload_json'])
        if table_exists(conn,'annotation_provenance'):
            from app.storage.provenance import reviewed_source
            try:
                if not reviewed_source(conn,row):continue
            except ValueError:continue
        if row['rule_revision'] not in SUPPORTED_RULE_REVISIONS:continue
        try:
            if not _unchanged_materials(conn,data,bank_id,row,read_view=read_view):continue
            dependencies = json.loads(row['dependencies_json'])
            now = concept_dependencies(conn, list(dependencies),read_view=read_view)
            # A reviewed ID merge can preserve a definition, but changed
            # mathematical conditions or ancestry require affected reanalysis.
            resolved = {old: read_view.resolve(old) if read_view is not None else catalog.resolve(conn, old) for old in dependencies}
            if set(now) != set(resolved.values()) or any(now.get(resolved[old]) != sha for old, sha in dependencies.items()):continue
        except ValueError:
            continue
        return {'id': row['id'], 'bank_id': bank_id, 'source_bank_id': row['bank_id'],
                'entity_id': row['entity_id'], 'catalog_revision': row['catalog_revision'],
                'current_catalog_revision': catalog.active_id(conn), 'content_revision': row['content_revision'],
                'material_revision': row['material_revision'], 'rule_revision': row['rule_revision'], 'analysis': item}
    return None


def prepared_summary(annotation):
    if annotation.get('cache_provenance'):
        return {'cache_provenance': annotation['cache_provenance'],
                'bindings': annotation['analysis']['bindings'],
                'reading': '这是已明确接受的共享原子/环节索引，包不含解法或本机数学核验。须实际读本题和参考独立判断训练价值，不能声称已复用一份不存在的推导。'}
    return {k: annotation['analysis'][k] for k in ('reference_reasoning','answer_check','bindings','methods','checkpoints','fingerprint')}


def matching(conn, data, *, topic_ids, stages=None, methods=None):
    """Unpaged, ready matches for application-level history filtering."""
    if (not isinstance(topic_ids, list) or not 1 <= len(topic_ids) <= 40
            or any(not isinstance(t, str) or not t for t in topic_ids)):
        raise ValueError('按原子检索须提供1–40个知识ID')
    if stages is not None and (not isinstance(stages,list) or any(not isinstance(s,str) for s in stages)
                               or not set(stages).issubset(STAGES)):
        raise ValueError('检验环节不合法')
    if methods is not None and (not isinstance(methods,list) or len(methods)>40
                                or any(not isinstance(m,str) or not 1<=len(m)<=200 for m in methods)):
        raise ValueError('检索方法须为文字数组')
    release = catalog.document(conn)
    if not release:raise ValueError('请先发布统一知识目录')
    children = {}
    for node in release['document']['nodes']:
        children.setdefault(node['parent_id'],[]).append(node['id'])
    selected = set()
    for tid in topic_ids:
        resolved = catalog.resolve(conn, tid, release['id'])
        if not resolved:raise ValueError('检索知识节点不存在')
        pending=[resolved]
        while pending:
            current_id=pending.pop()
            if current_id in selected:continue
            selected.add(current_id);pending.extend(children.get(current_id,()))
    selected.update(r['old_id'] for r in release['document']['redirects'] if r['target_id'] in selected)
    ordered = sorted(selected);candidate_ids = set()
    for start in range(0, len(ordered), 400):
        chunk = ordered[start:start + 400]
        candidate_ids.update(r[0] for r in conn.execute('''SELECT DISTINCT l.bank_id FROM question_annotation_topics t
            JOIN question_annotation_links l ON l.annotation_id=t.annotation_id WHERE t.topic_id IN ('''
            + ','.join('?' for _ in chunk) + ')', chunk))
        from app.storage.annotation_cache import exists
        if exists(conn):
            candidate_ids.update(r[0] for r in conn.execute('''SELECT DISTINCT a.bank_id FROM imported_annotation_topics t
                JOIN imported_question_annotations a ON a.id=t.annotation_id WHERE t.topic_id IN ('''
                + ','.join('?' for _ in chunk) + ')', chunk))
    matches = [];entities = set();emitted_aliases = set()
    # A category prefix must not select the representative of an alias group.
    for bid in sorted(candidate_ids,key=lambda value:hashlib.sha256(value.encode()).digest()):
        item = current(conn, data, bid)
        if not item or item['analysis']['status'] != 'ready':continue
        bindings = item['analysis']['bindings']
        if not any(catalog.resolve(conn, b['topic_id']) in selected and (not stages or set(b['stages']).intersection(stages)) for b in bindings):continue
        if methods and not (set(methods).intersection(item['analysis']['methods'])
                            or {catalog.digest(m) for m in methods}.intersection(item['analysis'].get('method_hashes', []))):continue
        from app.bank.access import access
        related = aliases(conn, bid)
        if any(access(conn, alias)['reserved'] for alias in related):continue
        # A revoked identity must split today's candidate groups, while the
        # annotation's historical entity ID remains immutable in storage.
        entity_id='question-' + uuid.uuid5(uuid.NAMESPACE_URL, 'mathlens:bank:' + min(related)).hex
        if entity_id in entities or related.intersection(emitted_aliases):continue
        entities.add(entity_id)
        emitted_aliases.update(related)
        item['entity_id']=entity_id
        item['alternate_bank_ids'] = sorted(related)
        matches.append(item)
    return release['id'], matches


def search(conn, data, *, topic_ids, stages=None, methods=None, offset=0, limit=30):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError('按原子检索须提供合法分页')
    revision,matches=matching(conn,data,topic_ids=topic_ids,stages=stages,methods=methods)
    return {'catalog_revision': revision, 'total': len(matches), 'items': matches[offset:offset+limit],
            'offset': offset, 'limit': limit, 'scope': '仅已就绪且依赖有效的通用题目标注；不按数学类别过滤。'}
