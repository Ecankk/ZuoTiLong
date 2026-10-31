"""Known topic candidates from an immutable selected-question result.

Hints are internal navigation, not a new mapping, a definition-read receipt,
or a statement that an entire bank question was assigned to the student.
"""
from app.storage.boundaries import table_exists
import json
import uuid

from app.knowledge import catalog, mapping_versions
from app.storage import annotation_cache


def _exists(conn, table):
    return bool(table_exists(conn, table))


def for_sources(conn, inputs, sources):
    if inputs.get('contract_version') != '1.8':
        return []
    if not all(_exists(conn, name) for name in ('learning_results', 'practice_question_bindings')):
        return []
    nodes = {node['id']: node for node in inputs['knowledge_catalog']}
    release = inputs.get('knowledge_catalog_revision')

    def canonical(tid):
        if tid in nodes:
            return tid
        if release and release.startswith('catalog-'):
            result = catalog.resolve(conn, tid, release)
            return result if result in nodes else None
        return None

    def describe(ids):
        return [{'id': tid, 'name': nodes[tid]['name'],
                 'kind': nodes[tid].get('origin', {}).get('node_kind')}
                for tid in sorted({canonical(tid) for tid in ids} - {None})]

    output = []
    for source in sources:
        if source['kind']=='question':
            from app.learning.paper_knowledge import topic_hint
            hint=topic_hint(conn,source,inputs['knowledge_catalog'])
            if hint:
                output.append({**hint,'question_topics':describe(hint['topic_ids']),
                    'original_target_topics':[],'reading':hint['basis']+' 仍须实际读取捕获定义，不能把整题表现扩散到全部原子。'})
            continue
        if source['kind'] != 'probe':
            continue
        content = source['content']
        assignment = content.get('assignment', {})
        result_id = assignment.get('source_result_id')
        probe_id, bank_id = content.get('probe_id'), content.get('bank_id')
        if not result_id or source['source_id'] != probe_id or assignment.get('bank_id') != bank_id:
            continue
        row = conn.execute('SELECT kind,paper_id,payload_json FROM learning_results WHERE id=?', (result_id,)).fetchone()
        if not row or row['kind'] != 'prepare_practice' or row['paper_id'] != source['paper_id']:
            continue
        envelope = json.loads(row['payload_json'])
        if envelope.get('schema_version') != '1.9':
            continue
        result = envelope['result']
        exercise = next((item for item in result['exercises']
                         if item['bank_id'] == bank_id and
                         'probe-' + uuid.uuid5(uuid.NAMESPACE_URL, result_id + ':' + item['id']).hex == probe_id), None)
        if not exercise:
            continue
        binding = conn.execute('SELECT * FROM practice_question_bindings WHERE result_id=? AND probe_id=?',
                               (result_id, probe_id)).fetchone()
        if not binding or binding['bank_id'] != bank_id or binding['annotation_id'] != exercise['annotation_id']:
            continue
        frozen = json.loads(binding['payload_json'])
        if (frozen['bank_id'] != binding['bank_id'] or frozen['annotation_id'] != binding['annotation_id'] or
                frozen['content_revision'] != binding['content_revision'] or
                frozen['material_revision'] != binding['material_revision']):
            continue
        annotation = annotation_cache.record(conn, binding['annotation_id'])
        if (not annotation or annotation['content_revision'] != frozen['annotation_content_revision'] or
                annotation['material_revision'] != frozen['annotation_material_revision']):
            continue
        analysis = json.loads(annotation['payload_json'])
        if analysis['status'] != 'ready':
            continue
        # Use the captured task's definitions, never the latest live release.
        # A stale annotation can still be kept as history but is no shortcut
        # to a new mathematical mapping.
        old = json.loads(annotation['dependencies_json'])
        resolved = {tid: canonical(tid) for tid in old}
        if not old or any(tid is None for tid in resolved.values()):
            continue
        current = mapping_versions.dependencies(inputs['knowledge_catalog'], resolved.values())
        if set(current) != set(resolved.values()) or any(current[resolved[tid]] != sha for tid, sha in old.items()):
            continue
        goals = [goal for goal in result['goals'] if goal['id'] in exercise['goal_ids']]
        question_topics = describe([item['topic_id'] for item in analysis['bindings']])
        target_topics = describe([tid for goal in goals for tid in goal['topic_ids']])
        output.append({'source_id': source['source_id'], 'selection_result_id': result_id,
                       'annotation_id': annotation['id'], 'question_topics': question_topics,
                       'original_target_topics': target_topics,
                       'reading': '这些是已选题和原训练目标的既有关联，仅作目录定位。按本次布置范围选择，'
                                  '题库整题标签不等于已布置全部小问；仍须读取捕获定义。'
                                  '这些线索不登记定义已读、不证明作答表现，也不授权新增考点。'})
    return output
