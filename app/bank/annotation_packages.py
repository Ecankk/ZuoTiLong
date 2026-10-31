"""Portable prepared-question indices: no question text or invented AI receipts."""
import json
import re
import uuid
from collections import Counter

from app.bank import annotations
from app.bank.access import aliases
from app.knowledge import catalog
from app.storage import annotation_cache as store
from app.common import now_iso

FORMAT = 'mathlens.question-index/v1'
POLICY = 'explicitly_accepted_source_index_not_locally_regraded'
SHA = re.compile(r'^[0-9a-f]{64}$')
ENTRY_FIELDS = {'role_hashes', 'dependencies', 'bindings', 'method_hashes',
                'fingerprint_sha256', 'origin_evidence_sha256', 'rule_revision', 'sha256'}


def _sha(value):
    return catalog.digest({k: v for k, v in value.items() if k != 'sha256'})


def role_hashes(materials):
    return {role: value['sha256'] for role, value in materials.items()}


def dependencies_match(conn, entry, *, read_view=None):
    try:
        old = entry['dependencies']
        now = annotations.concept_dependencies(conn, list(old), read_view=read_view)
        resolved = {tid: read_view.resolve(tid) if read_view is not None else catalog.resolve(conn, tid) for tid in old}
        return set(now) == set(resolved.values()) and all(now.get(resolved[t]) == sha for t, sha in old.items())
    except (ValueError, KeyError):
        return False


def validate_package(package):
    if (not isinstance(package, dict) or set(package) != {'schema_version', 'provenance', 'dependency_fields', 'entries', 'sha256'}
            or package['schema_version'] != FORMAT or package['provenance'] != POLICY
            or package['dependency_fields'] != list(annotations.DEPENDENCY_FIELDS)):
        raise ValueError('共享题目标注索引字段或版本不合法')
    if len(catalog.encode(package).encode()) > 16 * 1024 * 1024:
        raise ValueError('共享题目标注索引过大')
    if not isinstance(package['sha256'], str) or not SHA.fullmatch(package['sha256']) or _sha(package) != package['sha256']:
        raise ValueError('共享标注索引散列不匹配')
    entries = package['entries']
    if not isinstance(entries, list) or not 1 <= len(entries) <= 10000:
        raise ValueError('共享标注索引条目数量不合法')
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
            raise ValueError('共享索引不能夹带题干、推导、个人信息或未知字段')
        if (not isinstance(entry['sha256'], str) or not SHA.fullmatch(entry['sha256'])
                or _sha(entry) != entry['sha256'] or entry['sha256'] in seen):
            raise ValueError('共享索引条目散列不匹配或重复')
        seen.add(entry['sha256'])
        roles = entry['role_hashes']
        if (not isinstance(roles, dict) or 'question' not in roles or not set(roles).issubset({'question', 'answer', 'analysis'})
                or not set(roles).intersection({'answer', 'analysis'})
                or any(not isinstance(v, str) or not SHA.fullmatch(v) for v in roles.values())):
            raise ValueError('共享索引缺少完整题干/参考散列')
        deps = entry['dependencies']
        if (not isinstance(deps, dict) or not 1 <= len(deps) <= 300
                or any(not isinstance(k, str) or not catalog.ID.fullmatch(k)
                       or not isinstance(v, str) or not SHA.fullmatch(v) for k, v in deps.items())):
            raise ValueError('共享索引知识依赖不合法')
        bindings = entry['bindings']
        if not isinstance(bindings, list) or not 1 <= len(bindings) <= 30:
            raise ValueError('共享索引原子关联不合法')
        topics = set()
        for b in bindings:
            if (not isinstance(b, dict) or set(b) != {'topic_id', 'role', 'stages'}
                    or not isinstance(b['topic_id'], str) or b['topic_id'] not in deps or b['topic_id'] in topics or b['role'] not in annotations.ROLES
                    or not isinstance(b['stages'], list) or not 1 <= len(b['stages']) <= 6
                    or any(s not in annotations.STAGES for s in b['stages']) or len(set(b['stages'])) != len(b['stages'])):
                raise ValueError('共享索引原子/环节关联无效')
            topics.add(b['topic_id'])
        if not any(b['role'] == 'primary' for b in bindings):
            raise ValueError('共享索引必须包含主要原子')
        if (not isinstance(entry['method_hashes'], list) or len(entry['method_hashes']) > 120
                or any(not isinstance(s, str) or not SHA.fullmatch(s) for s in entry['method_hashes'])
                or len(set(entry['method_hashes'])) != len(entry['method_hashes'])):
            raise ValueError('共享索引方法散列无效')
        if (entry['rule_revision'] not in annotations.SUPPORTED_RULE_REVISIONS
                or any(not isinstance(entry[k], str) or not SHA.fullmatch(entry[k])
                       for k in ('fingerprint_sha256', 'origin_evidence_sha256'))):
            raise ValueError('共享索引规则或出处散列无效')
    return {'sha256': package['sha256'], 'entries': len(entries), 'provenance': POLICY,
            'included': '原子/环节及材料、方法、指纹散列', 'excluded': '题干/答案/图片/推导/个人记录/会话与AI回执',
            'trust_notice': '散列验证内容一致，不能证明数学正确或发布者；导入前须明确接受来源。'}


def _local_proof(conn, annotation, actual):
    from app.storage.provenance import reviewed_source
    proof = reviewed_source(conn, annotation)
    local=conn.execute('SELECT 1 FROM learning_results r JOIN question_annotations a ON a.result_id=r.id WHERE a.id=?',(annotation['id'],)).fetchone()
    if proof and not local:
        source = proof['source']
        if (source['identity'].get(annotation['bank_id']) != actual['question']['sha256']
                or role_hashes(source['materials']) != role_hashes(actual)):
            raise ValueError('通用标注出处未核验该题干及全部参考版本')
        return catalog.digest(proof)
    row = conn.execute('''SELECT t.*,r.payload_sha256,r.payload_json AS result_json
        FROM question_annotations a JOIN learning_results r ON r.id=a.result_id
        JOIN learning_tasks t ON t.id=r.task_id WHERE a.id=?''', (annotation['id'],)).fetchone()
    if not row or row['status'] != 'completed' or row['kind'] != 'annotate_questions':
        raise ValueError('标注尚缺已完成的原始Agent交付，不能作为共享就绪索引')
    inputs = json.loads(row['input_json'])
    source = next((q for q in inputs['bank_questions'] if q['bank_id'] == annotation['source_bank_id']), None)
    if (not source or source['identity'].get(annotation['bank_id']) != actual['question']['sha256']
            or role_hashes(source['materials']) != role_hashes(actual)
            or source['material_revision'] != catalog.digest(source['materials'])):
        raise ValueError('标注原交付未核验该题干及全部参考版本')
    result = json.loads(row['result_json'])
    if annotation['analysis'] not in result['result']['questions']:
        raise ValueError('标注与原交付内容不一致')
    for role, value in source['materials'].items():
        read = conn.execute('''SELECT sha256 FROM task_reads WHERE task_id=? AND run_token=?
            AND kind='bank_preparation' AND record_id=? AND role=?''', (row['id'], row['run_token'], source['bank_id'], role)).fetchone()
        if not read or read[0] != value['sha256']:
            raise ValueError('标注原材料阅读凭据缺失，不能导出')
    return catalog.digest({'input_revision': row['input_revision'], 'result_sha256': row['payload_sha256'],
                           'reviewed_roles': role_hashes(source['materials'])})


def export_package(conn, data):
    entries = {}
    for row in conn.execute("SELECT id FROM bank_questions WHERE source!='本地示例题库' ORDER BY id"):
        try:
            value = annotations.current(conn, data, row[0])
            if not value or value['analysis']['status'] != 'ready':
                continue
            if value.get('cache_provenance'):
                item = store.entry(conn, store.record(conn, value['id']))
                if item:
                    entries[item['sha256']] = item
                continue
            actual = annotations.materials(conn, data, row[0])
            evidence = _local_proof(conn, value, actual)
        except ValueError:
            # Unfinished/unproven source records remain local. Never replace
            # them with invented receipts just to enlarge an export.
            continue
        canonical = {}
        for b in value['analysis']['bindings']:
            tid = catalog.resolve(conn, b['topic_id'])
            previous = canonical.get(tid)
            role = min((previous['role'], b['role']), key=annotations.ROLES.index) if previous else b['role']
            stages = set(b['stages']) | (set(previous['stages']) if previous else set())
            canonical[tid] = {'topic_id': tid, 'role': role, 'stages': [s for s in annotations.STAGES if s in stages]}
        bindings = list(canonical.values())
        entry = {'role_hashes': role_hashes(actual),
                 'dependencies': annotations.concept_dependencies(conn, [b['topic_id'] for b in bindings]),
                 'bindings': sorted(bindings, key=lambda b: b['topic_id']),
                 'method_hashes': sorted({catalog.digest(m) for m in value['analysis']['methods']}),
                 'fingerprint_sha256': catalog.digest(value['analysis']['fingerprint']),
                 'origin_evidence_sha256': evidence, 'rule_revision': value['rule_revision']}
        entry['sha256'] = _sha(entry)
        entries[entry['sha256']] = entry
    if not entries:
        raise ValueError('没有材料/知识依赖有效且交付出处完整的就绪标注可导出')
    package = {'schema_version': FORMAT, 'provenance': POLICY,
               'dependency_fields': list(annotations.DEPENDENCY_FIELDS),
               'entries': [entries[k] for k in sorted(entries)]}
    package['sha256'] = _sha(package)
    validate_package(package)
    return package


def preview(conn, data, package):
    description = validate_package(package)
    release = catalog.document(conn)
    if not release:
        raise ValueError('请先导入或发布统一考点目录，再核对题目标注索引')
    nodes = {n['id']: n for n in release['document']['nodes']}
    lookup = {}
    issues = Counter()
    for entry in package['entries']:
        if (not dependencies_match(conn, entry)
                or any(not catalog.resolve(conn, b['topic_id'])
                       or nodes[catalog.resolve(conn, b['topic_id'])]['kind'] != 'atom' for b in entry['bindings'])):
            issues['knowledge_mismatch'] += 1
            continue
        lookup.setdefault(catalog.digest(entry['role_hashes']), []).append(entry)
    matches = []
    for row in conn.execute("SELECT id FROM bank_questions WHERE source!='本地示例题库' ORDER BY id"):
        bid = row[0]
        try:
            actual = annotations.materials(conn, data, bid)
        except ValueError:
            issues['local_material_unreadable'] += 1
            continue
        candidates = lookup.get(catalog.digest(role_hashes(actual)), [])
        if not candidates:
            continue
        # Two differing index judgments about the exact same materials require
        # review; file order cannot silently choose one of them.
        decisions = {catalog.digest({k: e[k] for k in ('dependencies', 'bindings', 'method_hashes', 'fingerprint_sha256')})
                     for e in candidates}
        if len(decisions) != 1:
            issues['conflicting_entries'] += 1
            continue
        current = annotations.current(conn, data, bid)
        if current:
            issues['already_reviewed_locally' if not current.get('cache_provenance') else 'already_imported'] += 1
            continue
        entry = sorted(candidates, key=lambda e: e['sha256'])[0]
        matches.append({'bank_id': bid, 'entry_sha256': entry['sha256'],
                        'content_revision': actual['question']['sha256'], 'material_revision': catalog.digest(actual)})
    token = catalog.digest({'package_sha256': package['sha256'], 'catalog_revision': release['id'], 'matches': matches,
                            'issues': dict(issues)})
    return {**description, 'catalog_revision': release['id'], 'matched_local_records': len(matches),
            'matches': matches, 'omitted': dict(issues), 'preview_sha256': token}


def import_package(conn, data, package, *, trusted_sha256, expected_preview_sha256, confirmed):
    if confirmed is not True or trusted_sha256 != package.get('sha256'):
        raise ValueError('请明确接受共享标注来源及可信散列；不会冒充本机重新核验')
    with catalog.atomic(conn):
        prepared = preview(conn, data, package)
        old = conn.execute('SELECT 1 FROM annotation_cache_imports WHERE package_sha256=? AND preview_sha256=?',
                           (package['sha256'], expected_preview_sha256)).fetchone()
        if old and not prepared['matches']:
            return {'sha256': package['sha256'], 'imported': 0, 'reused': True}
        if prepared['preview_sha256'] != expected_preview_sha256:
            raise ValueError('本地材料、目录或已有标注已变化，请重新预览共享索引')
        existing = conn.execute('SELECT payload_json FROM annotation_cache_packages WHERE sha256=?', (package['sha256'],)).fetchone()
        if existing and json.loads(existing[0]) != package:
            raise ValueError('同散列共享索引内容冲突')
        if not existing:
            conn.execute('INSERT INTO annotation_cache_packages VALUES(?,?,?)', (package['sha256'], catalog.encode(package), now_iso()))
            conn.execute('INSERT INTO annotation_cache_state VALUES(?,1)', (package['sha256'],))
        elif not store.enabled(conn, package['sha256']):
            raise ValueError('该共享索引已停用，请明确恢复其启用状态后重新预览')
        entries = {e['sha256']: e for e in package['entries']}
        for match in prepared['matches']:
            bid = match['bank_id']; entry = entries[match['entry_sha256']]
            aid = 'cached-annotation-' + catalog.digest({'package': package['sha256'], 'bank_id': bid, 'entry': entry['sha256']})
            entity = 'question-' + uuid.uuid5(uuid.NAMESPACE_URL, 'mathlens:bank:' + min(aliases(conn, bid))).hex
            store.register(conn, aid)
            conn.execute('INSERT INTO imported_question_annotations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                         (aid, package['sha256'], entry['sha256'], bid, entity, match['content_revision'],
                          match['material_revision'], prepared['catalog_revision'], catalog.encode(entry['dependencies']),
                          catalog.encode(entry), now_iso()))
            for binding in entry['bindings']:
                conn.execute('INSERT INTO imported_annotation_topics VALUES(?,?,?,?)',
                             (aid, binding['topic_id'], binding['role'], catalog.encode(binding['stages'])))
        receipt = 'index-import-' + catalog.digest({'package': package['sha256'], 'preview': expected_preview_sha256})
        conn.execute('INSERT OR IGNORE INTO annotation_cache_imports VALUES(?,?,?,?)',
                     (receipt, package['sha256'], expected_preview_sha256, now_iso()))
    return {'sha256': package['sha256'], 'imported': len(prepared['matches']), 'reused': False,
            'provenance': POLICY, 'local_agent_tasks_created': 0}


def set_enabled(conn, sha256, enabled, *, confirmed):
    if confirmed is not True or type(enabled) is not bool:
        raise ValueError('启停共享标注索引需要明确确认')
    if not conn.execute('SELECT 1 FROM annotation_cache_packages WHERE sha256=?', (sha256,)).fetchone():
        raise ValueError('该共享索引尚未导入')
    conn.execute('UPDATE annotation_cache_state SET enabled=? WHERE package_sha256=?', (int(enabled), sha256))
    return {'sha256': sha256, 'enabled': enabled, 'history_preserved': True}


def cache_current(conn, data, row, *, read_view=None):
    entry = json.loads(row['metadata_json'])
    if _sha(entry) != row['entry_sha256'] or entry['sha256'] != row['entry_sha256']:
        return None
    if entry['rule_revision'] not in annotations.SUPPORTED_RULE_REVISIONS or not dependencies_match(conn, entry, read_view=read_view):
        return None
    actual = read_view.materials(row['bank_id']) if read_view is not None else annotations.materials(conn, data, row['bank_id'])
    if (role_hashes(actual) != entry['role_hashes'] or catalog.digest(actual) != row['material_revision']
            or actual['question']['sha256'] != row['content_revision']):
        return None
    return {'id': row['id'], 'bank_id': row['bank_id'], 'source_bank_id': row['bank_id'],
            'entity_id': row['entity_id'], 'catalog_revision': row['catalog_revision'],
            'current_catalog_revision': catalog.active_id(conn), 'content_revision': row['content_revision'],
            'material_revision': row['material_revision'], 'rule_revision': entry['rule_revision'],
            'cache_provenance': {'package_sha256': row['package_sha256'], 'entry_sha256': row['entry_sha256'], 'policy': POLICY},
            'analysis': store.analysis(row)}


def require_reference_proof(conn, row, manifest):
    entry = store.entry(conn, row)
    if (not entry or _sha(entry) != row['entry_sha256'] or entry != json.loads(row['metadata_json'])
            or entry['role_hashes'] != role_hashes(manifest['resources'])):
        raise ValueError('共享标注出处与练习固定题干/参考版本不一致')
    # Historical selected practice keeps the explicitly accepted immutable
    # origin; disabling only removes this package from new-question admission.
    return True
