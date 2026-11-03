"""Versioned reuse of prepared mathematics, separate from student judgments."""
import json

from app.bank import annotations, paper_candidates
from app.bank.access import require_access
from app.knowledge import catalog, index, mapping_versions
from app.storage import annotation_cache

VERSION = '2.0'


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS paper_question_bindings(
        report_id TEXT NOT NULL REFERENCES agent_reports(id),
        question_id TEXT NOT NULL REFERENCES questions(id),
        result_id TEXT NOT NULL REFERENCES learning_results(id),
        bank_id TEXT NOT NULL REFERENCES bank_questions(id),
        annotation_id TEXT NOT NULL REFERENCES prepared_annotation_ids(id),
        source_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,
        PRIMARY KEY(report_id,question_id))''')


def capture(conn, data, paper, selected_number=None):
    paper = dict(paper)
    located = paper_candidates.locate(conn, paper, selected_number=selected_number)
    nodes = index.catalog(conn);lookup = {n['id']: n for n in nodes}
    entries = []
    for group in located['candidates']:
        for source in group['sources']:
            bid = source['bank_id'];annotation = annotations.current(conn, data, bid)
            if not annotation or annotation['analysis']['status'] != 'ready':continue
            row = annotation_cache.record(conn, annotation['id'])
            if not row:continue
            from app.learning.practice_knowledge import material_binding
            topics = {catalog.resolve(conn, b['topic_id']) for b in annotation['analysis']['bindings']}
            if None in topics or not topics.issubset(lookup):continue
            closure = mapping_versions.dependencies(nodes, topics)
            entries.append({'number': group['number'], 'bank_id': bid,
                'binding': material_binding(conn, data, bid, annotation),
                'materials': annotations.materials(conn, data, bid),
                'annotation_record_sha256': catalog.digest(dict(row)),
                'prepared': annotations.prepared_summary(annotation),
                'topic_ids': sorted(topics), 'dependencies': closure})
    return {'locator': located, 'catalog_revision': mapping_versions.catalog_revision(nodes),
            'catalog_nodes': nodes, 'entries': entries,
            'policy': '候选并非同题。先读原卷与候选题干，逐项对照条件、目标和选项/图；仅确认等价后复用固定版本。无合适参考仍独立分析，不猜配或要求学生确认。'}


def manifest(inputs):
    scope = inputs['paper_knowledge']
    return {'catalog_revision': scope['catalog_revision'], 'policy': scope['policy'],
            'locator': scope['locator'],
            'candidates': [{'number': e['number'], 'bank_id': e['bank_id'],
                'annotation_id': e['binding']['annotation_id'], 'available_roles': list(e['materials']),
                'topic_ids': e['topic_ids']} for e in scope['entries']],
            'reading': 'read_bank可用role=all取得该候选固定材料和通用标注；task_context的bank_ids读取通用分析、topic_ids读取捕获定义。references只记录实际核对等价的题，其余留空；不重编通用考点。'}


def _entry(inputs, bank_id, number=None):
    candidates = [e for e in inputs['paper_knowledge']['entries'] if e['bank_id'] == bank_id
                  and (number is None or e['number'] == number)]
    if not candidates:raise ValueError('题目不属于本任务捕获的原卷参考候选')
    return candidates[0]


def _current(conn, data, entry):
    require_access(conn, entry['bank_id'], internal=True)
    if annotations.materials(conn, data, entry['bank_id']) != entry['materials']:
        raise ValueError('原卷参考材料已变化；勿替换固定版本，可独立分析或另建任务')
    row = annotation_cache.record(conn, entry['binding']['annotation_id'])
    if row is None or catalog.digest(dict(row)) != entry['annotation_record_sha256']:
        raise ValueError('原卷参考出处已变化')
    annotation = annotations.current(conn, data, entry['bank_id'])
    if (not annotation or annotation['analysis']['status'] != 'ready'
            or annotation['id'] != entry['binding']['annotation_id']):
        raise ValueError('原卷参考标注已变化或不再就绪，请重新核对')


def prepared_context(conn, data, task, lease, bank_ids):
    if (not isinstance(bank_ids, list) or not 1 <= len(bank_ids) <= 4
            or any(not isinstance(b, str) for b in bank_ids) or len(set(bank_ids)) != len(bank_ids)):
        raise ValueError('每次读取1–4个不同的捕获参考bank_ids')
    inputs = json.loads(task['input_json']);output = []
    from app.learning.tasks import record_read
    for bid in bank_ids:
        entry = _entry(inputs, bid);_current(conn, data, entry)
        value = {'bank_id': bid, 'number': entry['number'], 'binding': entry['binding'],
                 'prepared_question': entry['prepared'], 'topic_ids': entry['topic_ids']}
        record_read(conn, lease, 'paper_reference', bid, 'annotation', catalog.digest(value))
        output.append(value)
    return {'paper_references': output, 'policy': inputs['paper_knowledge']['policy']}


def read(conn, data, task, lease, payload, image_content):
    if not task or task['kind'] not in ('analyze_paper', 'review_question'):return None
    inputs = json.loads(task['input_json'])
    if inputs.get('contract_version') != VERSION:return None
    bid = payload['bank_id']
    if not any(e['bank_id'] == bid for e in inputs['paper_knowledge']['entries']):return None
    entry = _entry(inputs, bid);_current(conn, data, entry)
    role = payload.get('role', 'question');roles = list(entry['materials']) if role == 'all' else [role]
    if not roles or any(r not in entry['materials'] for r in roles):raise ValueError('捕获的原卷参考没有该材料角色')
    images, resources = [], []
    from app.learning.tasks import record_read
    for current in roles:
        item = entry['materials'][current];position = None
        if item['path']:
            from app.storage.boundaries import material_path
            images.append(image_content(material_path(data,item['path']), data));position = len(images)
        resources.append({'role': current, 'text': item['text'], 'sha256': item['sha256'], 'image_index': position})
        record_read(conn, lease, 'paper_bank', bid, current, item['sha256'])
    context = prepared_context(conn, data, task, lease, [bid])
    result = {'bank_id': bid, 'resources': resources, **context,
              'internal_only': True, 'instruction': '这是任务捕获且当前仍有效的参考版本。先核原题实际相同，再验证/复用通用推导；学生作答、批改痕迹和可能错因必须从原卷单独检查。'}
    return [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}, *images]


def validate_input(conn, data, task, inputs, current, result):
    ordinary = lambda value: {k: v for k, v in value.items() if k != 'paper_knowledge'}
    if catalog.digest(ordinary(inputs)) != catalog.digest(ordinary(current)):
        raise ValueError('原卷任务证据已变化，拒绝覆盖新内容')
    references = result['references']
    numbers = [r['number'] for r in references]
    questions = result['report']['questions'] if task['kind'] == 'analyze_paper' else [result['question']]
    by_number = {q['number']: q for q in questions}
    if len(set(numbers)) != len(numbers) or not set(numbers).issubset(by_number):
        raise ValueError('每道实际分析的原题最多关联一份核对过的通用参考')
    from app.learning.tasks import require_read
    from app.learning.practice_knowledge import require_current_definitions
    scope = inputs['paper_knowledge'];nodes = {n['id']: n for n in scope['catalog_nodes']}
    for ref in references:
        entry = _entry(inputs, ref['bank_id'], ref['number'])
        if ref['annotation_id'] != entry['binding']['annotation_id']:
            raise ValueError('不能将原卷关联到其他标注版本')
        _current(conn, data, entry)
        require_current_definitions(conn, scope['catalog_nodes'], entry['topic_ids'])
        for role, item in entry['materials'].items():
            require_read(conn, task, 'paper_bank', entry['bank_id'], role, item['sha256'])
        context = {'bank_id': entry['bank_id'], 'number': entry['number'], 'binding': entry['binding'],
                   'prepared_question': entry['prepared'], 'topic_ids': entry['topic_ids']}
        require_read(conn, task, 'paper_reference', entry['bank_id'], 'annotation', catalog.digest(context))
        for topic in entry['topic_ids']:
            require_read(conn, task, 'paper_definition', topic, scope['catalog_revision'], catalog.digest(nodes[topic]))
        # Whole-page evidence is also required by ordinary analysis/review.
        # A reference cannot stand in for an unreadable/missing original stem.
        if by_number[ref['number']]['evidence_status'] != 'readable':
            raise ValueError('原题题意缺失或不清时不能确认与题库等价')
        if any(not value.strip() for value in ref['comparison'].values()):
            raise ValueError('须分别记录题目条件、目标及选项/图形的实际对照依据')


def save(conn, data, task, result_id, projection, inputs, result):
    from app.storage.practice_materials import freeze
    for ref in result['references']:
        entry = _entry(inputs, ref['bank_id'], ref['number'])
        row = conn.execute('SELECT id FROM questions WHERE paper_id=? AND number=?',
                           (task['paper_id'], ref['number'])).fetchone()
        if not row:raise ValueError('已分析原题记录缺失，不能保存参考关联')
        binding = freeze(conn, data, entry['binding'])
        payload = {**entry, 'binding': binding, 'comparison': ref['comparison'],
                   'catalog_nodes': [n for n in inputs['paper_knowledge']['catalog_nodes'] if n['id'] in entry['dependencies']]}
        conn.execute('INSERT INTO paper_question_bindings VALUES(?,?,?,?,?,?,?)',
            (projection['report_id'], row['id'], result_id, ref['bank_id'], ref['annotation_id'],
             inputs['source_sha256'], json.dumps(payload, ensure_ascii=False, sort_keys=True)))


def topic_hint(conn, source, captured_nodes):
    """Fixed, source-specific navigation; never a mastery judgment or new map."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='paper_question_bindings'").fetchone():return None
    content = source['content'];report_id = content.get('report_id')
    row = conn.execute('SELECT * FROM paper_question_bindings WHERE report_id=? AND question_id=?',
                       (report_id, source['source_id'])).fetchone()
    if not row:return None
    payload = json.loads(row['payload_json'])
    result = conn.execute('SELECT kind,paper_id,payload_json FROM learning_results WHERE id=?', (row['result_id'],)).fetchone()
    if not result or result['paper_id'] != source['paper_id'] or result['kind'] not in ('analyze_paper', 'review_question'):return None
    envelope = json.loads(result['payload_json'])
    if envelope.get('schema_version') != VERSION:return None
    ref = next((r for r in envelope['result']['references']
                if str(r['number']) == str(content['number']) and r['bank_id'] == row['bank_id']
                and r['annotation_id'] == row['annotation_id']), None)
    if ref is None or ref['comparison'] != payload['comparison']:return None
    report = conn.execute('SELECT paper_id,source_sha256 FROM agent_reports WHERE id=?', (report_id,)).fetchone()
    if not report or report['paper_id'] != source['paper_id'] or report['source_sha256'] != row['source_sha256']:return None
    origin = annotation_cache.record(conn, row['annotation_id'])
    if origin is None or catalog.digest(dict(origin)) != payload['annotation_record_sha256']:return None
    try:
        expected = payload['dependencies'];release = mapping_versions.catalog_revision(captured_nodes)
        canonical = lambda tid: catalog.resolve(conn, tid, release) if release.startswith('catalog-') else tid
        resolved = {tid: canonical(tid) for tid in expected}
        actual = mapping_versions.dependencies(captured_nodes, resolved.values())
        if set(actual) != set(resolved.values()) or any(actual.get(resolved[tid]) != value for tid, value in expected.items()):return None
        topics = sorted({canonical(tid) for tid in payload['topic_ids']})
    except ValueError:return None
    return {'source_id': source['source_id'], 'source_revision': source['source_revision'],
            'bank_id': row['bank_id'], 'annotation_id': row['annotation_id'], 'topic_ids': topics,
            'basis': '原卷已实际对照并绑定的通用题目版本；仅为知识导航，个人事件仍须按具体证据映射。'}
