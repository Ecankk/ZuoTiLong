"""Durable task inputs, scoped writes and transactional Agent result receipts.

The bridge owns execution leases. A result and its learning records commit in
one SQLite transaction; the session database is a recoverable UI projection.
"""
from __future__ import annotations

from app.storage.paths import paper_path, relative_file, resolve_file, connection_data
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from app.learning.contracts import KINDS, PREPARATION_KINDS, VERSION, result_schema, validate_result
from app.learning.text_integrity import validate_result_text
from app.learning.loop import apply_report, assess_attempt, revise_assessment, stamp
from app.bank.access import require_access, preferences, aliases
from app.learning.plans import practice_state, plan_goals


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def init_tasks(conn):
    for sql in (
        '''CREATE TABLE IF NOT EXISTS learning_tasks(
        id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,workflow_id TEXT NOT NULL,
        session_id TEXT NOT NULL,kind TEXT NOT NULL,paper_id TEXT REFERENCES papers(id),
        attempt_id TEXT,input_revision TEXT NOT NULL,input_json TEXT NOT NULL,
        status TEXT NOT NULL,run_token TEXT NOT NULL,turn_id TEXT,result_id TEXT,error TEXT,
        created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS learning_results(
        id TEXT PRIMARY KEY,task_id TEXT NOT NULL UNIQUE REFERENCES learning_tasks(id),
        paper_id TEXT REFERENCES papers(id),kind TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS task_reads(
        task_id TEXT NOT NULL REFERENCES learning_tasks(id),run_token TEXT NOT NULL,
        kind TEXT NOT NULL,record_id TEXT NOT NULL,role TEXT NOT NULL,sha256 TEXT NOT NULL,
        PRIMARY KEY(task_id,run_token,kind,record_id,role))''',
        '''CREATE TABLE IF NOT EXISTS practice_goals(
        id TEXT PRIMARY KEY,paper_id TEXT NOT NULL REFERENCES papers(id),
        result_id TEXT NOT NULL REFERENCES learning_results(id),payload_json TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS goal_questions(
        goal_id TEXT NOT NULL REFERENCES practice_goals(id),question_id TEXT NOT NULL REFERENCES questions(id),
        PRIMARY KEY(goal_id,question_id))''',
        '''CREATE TABLE IF NOT EXISTS probe_goals(
        probe_id TEXT NOT NULL REFERENCES diagnostic_probes(id),goal_id TEXT NOT NULL REFERENCES practice_goals(id),
        PRIMARY KEY(probe_id,goal_id))''',
        '''CREATE TABLE IF NOT EXISTS practice_plan_members(
        result_id TEXT NOT NULL REFERENCES learning_results(id),
        probe_id TEXT NOT NULL REFERENCES diagnostic_probes(id),
        PRIMARY KEY(result_id,probe_id))''',
        '''CREATE TABLE IF NOT EXISTS goal_related_probes(
        goal_id TEXT NOT NULL REFERENCES practice_goals(id),
        probe_id TEXT NOT NULL REFERENCES diagnostic_probes(id),
        PRIMARY KEY(goal_id,probe_id))''',
        '''CREATE UNIQUE INDEX IF NOT EXISTS idx_one_learning_task ON learning_tasks((1))
        WHERE status IN ('queued','running','result_saved','repairing')''',
    ):
        conn.execute(sql)
    from app.knowledge.index import initialize
    initialize(conn)
    from app.bank.annotations import initialize as initialize_annotations
    initialize_annotations(conn)
    from app.learning.practice_knowledge import initialize as initialize_practice_knowledge
    initialize_practice_knowledge(conn)
    from app.learning.paper_knowledge import initialize as initialize_paper_knowledge
    initialize_paper_knowledge(conn)
    from app.learning.practice_review import initialize as initialize_practice_reviews
    initialize_practice_reviews(conn)
    from app.learning.workflows import init_workflows
    init_workflows(conn)
    from app.knowledge.preparation import initialize as initialize_preparation
    initialize_preparation(conn)


@contextmanager
def atomic(conn):
    # SAVEPOINT works both in an explicit caller transaction and in autocommit.
    name = 'task_' + uuid.uuid4().hex
    conn.execute('SAVEPOINT ' + name)
    try:
        yield
    except BaseException:
        conn.execute('ROLLBACK TO ' + name)
        conn.execute('RELEASE ' + name)
        raise
    else:
        conn.execute('RELEASE ' + name)


def rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args)]


def resource_digest(path, data):
    path = Path(path).resolve()
    from app.storage.boundaries import library_root
    if not any(path.is_relative_to(p.resolve()) for p in (data, library_root(data))) or not path.is_file():
        raise ValueError('任务材料不在个人资料目录或已缺失')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_input(conn, root, data, kind, paper_id, attempt_id=None, *, contract_version=None, review_request=None, task_scope=None, knowledge_request=None,annotation_rule_revision=None):
    if kind in PREPARATION_KINDS:
        if paper_id is not None or attempt_id is not None:
            raise ValueError('通用知识任务不应关联或伪造学生试卷/作答')
        from app.knowledge.maintenance import capture
        return capture(conn, data, kind, task_scope,annotation_rule_revision=annotation_rule_revision)
    if task_scope is not None:raise ValueError('试卷任务不能夹带题库维护作用域')
    paper = conn.execute('SELECT * FROM papers WHERE id=?', (paper_id,)).fetchone()
    if not paper or paper['archived_at']:
        raise ValueError('试卷不存在或已归档')
    paper = dict(paper)
    if not paper.get('source_path'):
        raise ValueError('试卷缺少原始PDF')
    source_sha = resource_digest(paper_path(data,paper['source_path'],root), data)
    if kind=='review_practice':
        from app.learning.practice_review import capture
        return {'paper':{k:paper.get(k) for k in ('id','archived_at','source_path')},
                'source_sha256':source_sha,'practice_review':capture(conn,data,paper_id,review_request)}
    if kind=='organize_knowledge' and contract_version=='1.8':
        from app.knowledge import mapping_versions as versions
        from app.knowledge.index import catalog
        scope=versions.normalize_request(knowledge_request)
        nodes=catalog(conn)
        return {'paper':{k:paper.get(k) for k in ('id','archived_at','source_path')},
                'source_sha256':source_sha,'knowledge_request':scope,
                'knowledge_sources':versions.select_sources(conn,paper_id,scope),
                'knowledge_catalog':nodes,'knowledge_catalog_revision':versions.catalog_revision(nodes),
                'knowledge_rule_revision':versions.RULE_REVISION}
    if knowledge_request is not None:raise ValueError('只有1.8知识整理可以携带证据范围')
    result = {'paper': {k: paper.get(k) for k in ('id', 'archived_at', 'source_path', 'score',
               'total_score', 'score_confirmed_at', 'math_type')}, 'source_sha256': source_sha,
              'preferences': preferences(conn),
              'questions': rows(conn, 'SELECT * FROM questions WHERE paper_id=? ORDER BY id', (paper_id,)),
              'reports': rows(conn, 'SELECT * FROM agent_reports WHERE paper_id=? ORDER BY created_at,id', (paper_id,))}
    if kind not in ('analyze_paper', 'review_question'):
        result['probes'] = rows(conn, 'SELECT * FROM diagnostic_probes WHERE paper_id=? ORDER BY id', (paper_id,))
        result['attempts'] = rows(conn, '''SELECT a.* FROM probe_attempts a JOIN diagnostic_probes p ON p.id=a.probe_id
                                      WHERE p.paper_id=? ORDER BY a.created_at,a.id''', (paper_id,))
        result['prior_results'] = rows(conn, '''SELECT id,kind,payload_sha256 FROM learning_results
                                              WHERE paper_id=? ORDER BY created_at,id''', (paper_id,))
    if kind == 'prepare_practice':
        if contract_version in ('1.3','1.4','1.5','1.6','1.9'):
            state = practice_state(conn, paper_id)
            result['practice_plan'] = {'state': state, 'goals': plan_goals(conn, state),
                'retired_probe_ids': [r[0] for r in conn.execute('SELECT probe_id FROM retired_probes')]}
        result['history'] = rows(conn, '''SELECT a.*,p.bank_id,p.paper_id,pp.archived_at FROM probe_attempts a
                                         JOIN diagnostic_probes p ON p.id=a.probe_id JOIN papers pp ON pp.id=p.paper_id
                                         ORDER BY a.id''')
        result['other_questions'] = rows(conn, '''SELECT q.*,p.archived_at FROM questions q
                                                 JOIN papers p ON p.id=q.paper_id ORDER BY q.id''')
        result['bank'] = rows(conn, '''SELECT b.id,b.fingerprint_json,r.metadata_json,r.question_path,
                                      r.analysis_path,r.answer_path FROM bank_questions b
                                      JOIN bank_resources r ON r.bank_id=b.id ORDER BY b.id''')
        if contract_version=='1.9':
            from app.learning.practice_knowledge import capture
            result['practice_knowledge']=capture(conn,paper_id,data)
        if contract_version in ('1.5','1.6','1.9'):
            result['other_exercises']=rows(conn,'''SELECT d.*,p.archived_at FROM diagnostic_probes d
                JOIN papers p ON p.id=d.paper_id WHERE d.paper_id!=? ORDER BY d.id''',(paper_id,))
            result['other_plans']=[practice_state(conn,p[0]) for p in conn.execute(
                'SELECT id FROM papers WHERE id!=? ORDER BY id',(paper_id,))]
    if kind == 'review_question':
        from app.learning.question_review import capture_review
        result['question_review'] = capture_review(conn, root, data, paper_id, review_request)
    if kind == 'grade_attempt':
        attempt = next((a for a in result['attempts'] if a['id'] == attempt_id), None)
        if not attempt:
            raise ValueError('作答不属于当前试卷')
        from app.learning.loop import require_active_probe
        require_active_probe(conn,attempt['probe_id'])
        result['attempt_id'] = attempt_id
        result['image_sha256'] = []
        from app.storage.images import image_records, image_path
        for record in image_records(conn, json.loads(attempt['images_json'])):
            result['image_sha256'].append(resource_digest(image_path(record, data), data))
        if contract_version=='1.9':
            from app.learning.practice_knowledge import capture_grade
            result['grading_knowledge']=capture_grade(conn,data,attempt_id)
    if kind in ('analyze_paper','review_question') and contract_version=='2.0':
        from app.learning.paper_knowledge import capture
        result['paper_knowledge']=capture(conn,data,paper,result['question_review']['question']['number'] if kind=='review_question' else None)
    if kind=='organize_knowledge':
        from app.knowledge.index import pending_sources,catalog
        result['knowledge_sources']=pending_sources(conn,paper_id)
        result['knowledge_catalog']=catalog(conn)
    return result


def task_record(conn, task_id):
    row = conn.execute('SELECT * FROM learning_tasks WHERE id=?', (task_id,)).fetchone()
    if not row:
        raise ValueError('学习任务不存在')
    return dict(row)


def create_task(conn, root, data, kind, paper_id, session_id, request_id, attempt_id=None, workflow_id=None, *, review_request=None, task_scope=None, knowledge_request=None, contract_version=None):
    if kind not in KINDS or not session_id:
        raise ValueError('任务类型或学习会话无效')
    try:
        request_id = str(uuid.UUID(request_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('任务请求标识无效') from None
    if (kind == 'grade_attempt') != bool(attempt_id):
        raise ValueError('只有批改任务需要且必须提供作答标识')
    if kind == 'review_question':
        from app.learning.question_review import normalize_request
        review_request = normalize_request(review_request)
    elif kind=='review_practice':
        from app.learning.practice_review import normalize_request
        review_request=normalize_request(review_request)
    elif review_request is not None:
        raise ValueError('只有指定复核任务可以附加复核材料')
    if kind in PREPARATION_KINDS:
        from app.knowledge.maintenance import normalize_scope
        task_scope = normalize_scope(kind, task_scope)
    elif task_scope is not None:raise ValueError('试卷任务不能携带通用知识维护作用域')
    from app.learning.contracts import default_version
    task_version=contract_version or (default_version(kind) if kind in PREPARATION_KINDS or kind in ('organize_knowledge','review_practice') else VERSION)
    if kind=='grade_attempt':
        from app.learning.practice_knowledge import grading_contract
        task_version=grading_contract(conn,attempt_id,contract_version)
    result_schema(kind,task_version)
    if knowledge_request is not None and (kind!='organize_knowledge' or task_version!='1.8'):
        raise ValueError('只有1.8知识整理可以携带证据范围')
    with atomic(conn):
        old = conn.execute('SELECT * FROM learning_tasks WHERE request_id=?', (request_id,)).fetchone()
        if old:
            if (old['kind'], old['paper_id'], old['attempt_id'], old['session_id']) != (kind, paper_id, attempt_id, session_id):
                raise ValueError('同一请求不能用于不同任务或会话')
            if kind == 'review_question' and json.loads(old['input_json'])['question_review']['request'] != review_request:
                raise ValueError('同一复核请求不能更换材料')
            if kind=='review_practice' and json.loads(old['input_json'])['practice_review']['request']!=review_request:
                raise ValueError('同一练习复核请求不能更换范围或字段授权')
            if kind in PREPARATION_KINDS and json.loads(old['input_json'])['task_scope'] != task_scope:
                raise ValueError('同一通用知识任务不能更换作用域')
            prior=json.loads(old['input_json'])
            if contract_version is not None and prior.get('contract_version','1.0')!=contract_version:
                raise ValueError('同一任务不能更换契约版本')
            if knowledge_request is not None:
                from app.knowledge.mapping_versions import normalize_request
                if prior.get('knowledge_request')!=normalize_request(knowledge_request):
                    raise ValueError('同一知识整理请求不能更换证据范围')
            return dict(old)
        if conn.execute("SELECT 1 FROM learning_tasks WHERE status IN ('queued','running','result_saved','repairing')").fetchone():
            raise ValueError('上一项学习任务尚未完成')
        if kind=='organize_knowledge' and task_version=='1.8':
            from app.knowledge import mapping_versions as versions
            if knowledge_request is None:
                knowledge_request={'source_ids':[s['source_id'] for s in versions.select_sources(conn,paper_id)],'refresh':True}
            knowledge_request=versions.normalize_request(knowledge_request)
        inputs = capture_input(conn, root, data, kind, paper_id, attempt_id, contract_version=task_version,
                               review_request=review_request, task_scope=task_scope, knowledge_request=knowledge_request)
        inputs['contract_version']=task_version
        if kind=='prepare_practice':
            latest=conn.execute('SELECT report_json FROM agent_reports WHERE paper_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(paper_id,)).fetchone()
            report=json.loads(latest[0]) if latest else {}
            if report.get('review',{}).get('status')!='verified' or report.get('completion')!='complete':
                raise ValueError('原卷作答和批改尚未核对通过，请先核对分析，再准备练习')
            if report.get('source_sha256')!=inputs['source_sha256']:
                raise ValueError('原PDF已改变，请先重新核对原卷分析')
        tid = 'task-' + uuid.uuid5(uuid.NAMESPACE_URL, 'mathlens:' + request_id).hex
        now = stamp()
        conn.execute('''INSERT INTO learning_tasks(id,request_id,workflow_id,session_id,kind,paper_id,attempt_id,
                        input_revision,input_json,status,run_token,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,'queued',?,?,?)''',
                     (tid, request_id, workflow_id or tid, session_id, kind, paper_id, attempt_id,
                      digest(inputs), encode(inputs), uuid.uuid4().hex, now, now))
    return task_record(conn, tid)


def bind_turn(conn, task_id, session_id, run_token, turn_id):
    task = task_record(conn, task_id)
    if task['session_id'] != session_id or task['run_token'] != run_token:
        raise ValueError('任务执行代次或会话已过期')
    if task['turn_id'] and task['turn_id'] != turn_id:
        raise ValueError('任务已绑定其他执行轮次')
    if task['status'] not in ('queued', 'running', 'repairing', 'result_saved'):
        raise ValueError('任务已停止，不能重新绑定')
    conn.execute("UPDATE learning_tasks SET turn_id=?,status=CASE WHEN result_id IS NULL THEN 'running' ELSE 'result_saved' END,updated_at=? WHERE id=?",
                 (turn_id, stamp(), task_id))


def check_lease(conn, lease):
    if not isinstance(lease, dict) or not all(lease.get(k) for k in ('task_id', 'session_id', 'run_token', 'turn_id')):
        raise ValueError('缺少当前任务的可信执行身份')
    task = task_record(conn, lease['task_id'])
    if any(task[k] != lease[k] for k in ('session_id', 'run_token', 'turn_id')):
        raise ValueError('旧连接、旧轮次或其他会话不能写入当前任务')
    if task['status'] not in ('running', 'repairing', 'result_saved'):
        raise ValueError('该任务已停止或尚未开始')
    return task


def record_read(conn, lease, kind, record_id, role, sha256):
    task = check_lease(conn, lease)
    conn.execute('INSERT OR REPLACE INTO task_reads VALUES(?,?,?,?,?,?)',
                 (task['id'], task['run_token'], kind, str(record_id), role, sha256))


def require_read(conn, task, kind, record_id, role, sha256):
    row = conn.execute('''SELECT sha256 FROM task_reads WHERE task_id=? AND run_token=?
                          AND kind=? AND record_id=? AND role=?''',
                       (task['id'], task['run_token'], kind, str(record_id), role)).fetchone()
    if not row or row[0] != sha256:
        raise ValueError(f'尚未读取当前版本的材料：{kind}/{record_id}/{role}')


def receipt(conn, task_id):
    row = conn.execute('SELECT id,payload_sha256,created_at FROM learning_results WHERE task_id=?', (task_id,)).fetchone()
    return {'task_id': task_id, 'result_id': row['id'], 'sha256': row['payload_sha256'],
            'saved_at': row['created_at']} if row else None


def deliver(conn, root, data, payload, lease):
    with atomic(conn):
        task = check_lease(conn, lease)
        inputs=json.loads(task['input_json'])
        validate_result(payload, task['kind'],inputs.get('contract_version','1.0'))
        if payload['task_id'] != task['id'] or any(payload[k] != task[k] for k in ('kind', 'paper_id', 'input_revision')):
            raise ValueError('结果与任务范围或输入版本不一致')
        sha = digest(payload)
        previous = receipt(conn, task['id'])
        if previous:
            if previous['sha256'] != sha:
                raise ValueError('本任务已经交付其他结果；修订须另建明确任务')
            return {**previous, 'reused': True}
        frozen = {q['bank_id']: q['revision_base']['analysis']
                  for q in inputs.get('bank_questions', []) if q.get('revision_base')}
        validate_result_text(payload['result'], legacy_questions=frozen)
        current = capture_input(conn, root, data, task['kind'], task['paper_id'], task['attempt_id'],
                                contract_version=inputs.get('contract_version','1.0'),
                                review_request=inputs.get('question_review',inputs.get('practice_review',{})).get('request'),task_scope=inputs.get('task_scope'),
                                knowledge_request=inputs.get('knowledge_request'),
                                annotation_rule_revision=inputs.get('rule_revision') if task['kind']=='annotate_questions' else None)
        if 'contract_version' in inputs:current['contract_version']=inputs['contract_version']
        if task['kind']=='organize_knowledge' and inputs.get('contract_version')=='1.8':
            ignored={'knowledge_catalog','knowledge_catalog_revision','knowledge_rule_revision'}
            if digest({k:v for k,v in current.items() if k not in ignored})!=digest({k:v for k,v in inputs.items() if k not in ignored}):
                raise ValueError('任务证据已变化，拒绝覆盖新内容')
            from app.knowledge.mapping_versions import validate_current
            validate_current(conn,inputs,payload['result'])
            current=inputs
        elif task['kind']=='review_practice':
            from app.learning.practice_review import validate_input
            validate_input(conn,inputs,current)
            current=inputs
        elif inputs.get('contract_version')=='1.9' and task['kind'] in ('prepare_practice','grade_attempt'):
            from app.learning.practice_knowledge import validate_input
            validate_input(conn,task,inputs,current,payload['result'])
            current=inputs
        elif inputs.get('contract_version')=='2.0' and task['kind'] in ('analyze_paper','review_question'):
            from app.learning.paper_knowledge import validate_input
            validate_input(conn,data,task,inputs,current,payload['result'])
            current=inputs
        elif digest(current) != task['input_revision']:
            raise ValueError('任务材料已变化，拒绝覆盖新内容；保留输入后重新发起任务')
        result = payload['result']
        rid = 'result-' + uuid.uuid4().hex
        conn.execute('INSERT INTO learning_results VALUES(?,?,?,?,?,?,?)',
                     (rid, task['id'], task['paper_id'], task['kind'], sha, encode(payload), stamp()))
        if task['kind'] == 'maintain_catalog':
            from app.knowledge.maintenance import save
            result_projection = save(conn, task, current, result)
        elif task['kind'] == 'annotate_questions':
            from app.bank.annotations import save
            result_projection = save(conn, rid, current, result, data=data)
        elif task['kind']=='review_practice':
            from app.learning.practice_review import save
            result_projection=save(conn,task,rid,current,result)
        elif task['kind'] == 'review_question':
            from app.learning.question_review import merge_review
            scope = current['question_review']
            require_read(conn, task, 'question_review', scope['request']['question_id'], 'materials', digest(scope))
            report = merge_review(current, result, payload['author'])
            pages = {r['page'] for q in (scope['question'], result['question']) for r in q['regions']}
            if not pages:
                raise ValueError('请先读取原卷相关页后再核对本题')
            for page in pages:
                require_read(conn, task, 'paper', task['paper_id'], str(page), current['source_sha256'])
            result_projection = apply_report(conn, task['paper_id'], report, root,
                                              question_numbers={result['question']['number']})
        elif task['kind'] == 'analyze_paper':
            report = copy.deepcopy(result['report'])
            if report['source_sha256'] != current['source_sha256']:
                raise ValueError('分析结果与原PDF不一致')
            known = {int(q['number']) for q in current['questions'] if str(q['number']).isdigit()}
            if not known.issubset(set(range(1, report['expected_count'] + 1))):
                raise ValueError('报告遗漏已经定位的题目，不能缩小题数后声称整卷完成')
            import pymupdf
            with pymupdf.open(paper_path(data,current['paper']['source_path'],root)) as pdf:
                for page in range(1, len(pdf) + 1):
                    require_read(conn, task, 'paper', task['paper_id'], str(page), current['source_sha256'])
            report['probes'] = []
            report['completion']=result['completion']
            applied = apply_report(conn, task['paper_id'], report, root)
            if result['completion'] != 'complete':
                conn.execute("UPDATE papers SET import_status='partial_analysis' WHERE id=?", (task['paper_id'],))
            result_projection = applied
        elif task['kind'] == 'prepare_practice':
            result_projection = _save_plan(conn, data, task, rid, result)
            if inputs.get('contract_version')=='1.9':
                from app.learning.practice_knowledge import save_new_bindings
                save_new_bindings(conn,data,task,rid,result)
        elif task['kind'] == 'grade_attempt':
            if result['attempt_id'] != task['attempt_id']:
                raise ValueError('批改结果引用了其他作答')
            attempt = next(a for a in current['attempts'] if a['id'] == task['attempt_id'])
            require_read(conn, task, 'attempt', task['attempt_id'], 'response', digest(attempt))
            probe=next(p for p in current['probes'] if p['id']==attempt['probe_id'])
            if inputs.get('contract_version')=='1.9':
                from app.learning.practice_knowledge import require_grade
                require_grade(conn,task,current,result)
            else:require_bank_read(conn,data,task,probe['bank_id'])
            assessment = {**result, 'author': payload['author'], 'task_result_id': rid}
            result_projection = (revise_assessment(conn, task['attempt_id'], assessment, 'Agent按当前作答版本重新批改')
                                 if attempt['assessment_json'] else assess_attempt(conn, task['attempt_id'], assessment))
        elif task['kind']=='organize_knowledge':
            from app.knowledge.index import save
            for source in current['knowledge_sources']:
                require_read(conn,task,'knowledge',source['source_id'],'evidence',source['source_revision'])
            if inputs.get('contract_version')=='1.8':
                known={n['id']:n for n in inputs['knowledge_catalog']}
                for topic in {t for m in result['mappings'] for t in m['topic_ids']}:
                    if topic not in known:raise ValueError('知识映射引用了不存在的稳定考点')
                    require_read(conn,task,'knowledge_definition',topic,inputs['knowledge_catalog_revision'],digest(known[topic]))
            result_projection=save(conn,rid,current,result)
        else:
            for ref in result['source_refs']:
                _validate_reference(conn, task['paper_id'], ref)
            result_projection = {'summary_result_id': rid}
        if inputs.get('contract_version')=='2.0' and task['kind'] in ('analyze_paper','review_question'):
            from app.learning.paper_knowledge import save as save_paper_references
            save_paper_references(conn,data,task,rid,result_projection,inputs,result)
        conn.execute("UPDATE learning_tasks SET status='result_saved',result_id=?,error=NULL,updated_at=? WHERE id=?",
                     (rid, stamp(), task['id']))
        return {**receipt(conn, task['id']), 'projection': result_projection, 'reused': False}


def _validate_reference(conn, paper_id, ref):
    queries = {'question': 'SELECT paper_id FROM questions WHERE id=?',
               'report': 'SELECT paper_id FROM agent_reports WHERE id=?',
               'result': 'SELECT paper_id FROM learning_results WHERE id=?',
               'attempt': '''SELECT p.paper_id FROM probe_attempts a JOIN diagnostic_probes p ON p.id=a.probe_id WHERE a.id=?'''}
    row = conn.execute(queries[ref['kind']], (ref['id'],)).fetchone()
    if not row or row[0] != paper_id:
        raise ValueError('总结引用不存在或属于其他试卷')


def _save_plan(conn, data, task, result_id, result):
    paper_id = task['paper_id']
    inputs = json.loads(task['input_json'])
    explicit = inputs.get('contract_version') in ('1.3','1.4','1.5','1.6','1.9')
    previous = inputs.get('practice_plan', {}).get('state', {})
    retained = result.get('retained_exercises', [])
    linked = inputs.get('contract_version') in ('1.5','1.6','1.9')
    assigned=set()
    def unique_question(bank_id, *, retaining=False):
        if not linked:return
        group=aliases(conn,bank_id)
        if group.intersection(assigned) and not retaining:
            raise ValueError('同题的不同来源不能重复布置；请用一个练习关联多个目标')
        assigned.update(group)
    if explicit and previous.get('is_current'):
        review=inputs.get('practice_knowledge',{}).get('legacy_review',{})
        missing = set(previous['probe_ids']) - set(review) - {e['probe_id'] for e in retained}
        if missing:
            raise ValueError('追加须保留当前有效练习并关联本轮目标，不能静默丢弃：' + ','.join(sorted(missing)))
    qids = {int(r['number']): r['id'] for r in conn.execute('SELECT id,number FROM questions WHERE paper_id=?', (paper_id,))}
    goals = {}
    for goal in result['goals']:
        if not set(goal['question_numbers']).issubset(qids):
            raise ValueError('补强目标引用了不存在的原题')
        gid = 'goal-' + uuid.uuid5(uuid.NAMESPACE_URL, result_id + ':' + goal['id']).hex
        goals[goal['id']] = (gid, goal)
        conn.execute('INSERT INTO practice_goals VALUES(?,?,?,?)', (gid, paper_id, result_id, encode(goal)))
        for number in goal['question_numbers']:
            conn.execute('INSERT INTO goal_questions VALUES(?,?)', (gid, qids[number]))
    for item in retained:
        old = conn.execute('''SELECT * FROM diagnostic_probes WHERE id=? AND paper_id=?
          AND id NOT IN (SELECT probe_id FROM retired_probes)''', (item['probe_id'], paper_id)).fetchone()
        if not old:
            raise ValueError('保留练习不存在、已停用或属于其他试卷')
        require_access(conn, old['bank_id'], internal=True)
        unique_question(old['bank_id'],retaining=True)
        if inputs.get('contract_version')=='1.9' or not previous.get('is_current') or old['id'] not in previous.get('probe_ids', []):
            # A changed analysis cannot reactivate stale exercises solely by
            # listing their IDs; read their current materials again first.
            require_bank_read(conn, data, task, old['bank_id'],probe_id=old['id'])
        conn.execute('INSERT INTO practice_plan_members VALUES(?,?)', (result_id, old['id']))
        for local_id in item['goal_ids']:
            conn.execute('INSERT INTO probe_goals VALUES(?,?)', (old['id'], goals[local_id][0]))
    for exercise in result['exercises']:
        bank_id = exercise['bank_id']
        require_access(conn, bank_id, internal=True)
        require_bank_read(conn,data,task,bank_id)
        unique_question(bank_id)
        group=aliases(conn,bank_id) if linked else {bank_id}
        prior_matches=[dict(p) for p in conn.execute('''SELECT d.id,d.bank_id,d.paper_id,
            EXISTS(SELECT 1 FROM probe_attempts a WHERE a.probe_id=d.id) AS attempted
            FROM diagnostic_probes d JOIN papers p ON p.id=d.paper_id
            WHERE p.archived_at IS NULL AND d.id NOT IN (SELECT probe_id FROM retired_probes)''')
            if p['bank_id'] in group]
        if linked and any(not p['attempted'] for p in prior_matches):
            raise ValueError('本题或已确认同题已有待做记录，请保留本卷练习或用related_probe_ids引用原记录，不重复布置')
        prior = conn.execute('''SELECT p.id FROM diagnostic_probes p JOIN papers pp ON pp.id=p.paper_id
                                WHERE p.bank_id=? AND p.id NOT IN (SELECT probe_id FROM retired_probes)''', (bank_id,)).fetchone()
        pending = conn.execute('''SELECT p.id FROM diagnostic_probes p WHERE p.paper_id=? AND p.bank_id=?
          AND p.id NOT IN (SELECT probe_id FROM retired_probes)
          AND NOT EXISTS (SELECT 1 FROM probe_attempts a WHERE a.probe_id=p.id) LIMIT 1''',
          (paper_id, bank_id)).fetchone()
        if explicit and pending:
            raise ValueError('本卷已有该题待作答，请用retained_exercises复用并关联目标，勿重复建题：' + pending['id'])
        if (prior or linked and prior_matches) and not exercise['repeat_reason']:
            raise ValueError('该题已有练习记录，复用须说明间隔复习或再次检验理由')
        selected = [goals[g] for g in exercise['goal_ids']]
        anchor = selected[0][1]
        skill = anchor['topic_ids'][0] if anchor['topic_ids'] else anchor['id']
        pid = 'probe-' + uuid.uuid5(uuid.NAMESPACE_URL, result_id + ':' + exercise['id']).hex
        payload = {**exercise, 'question_number': anchor['question_numbers'][0],
                   'skill_id': skill, 'skill_label': anchor['label'],
                   'targets': anchor['evidence'], 'discriminates': exercise['selection_reason'],
                   'priority': min(g[1]['priority'] for g in selected), 'accepted': [],
                   'source_result_id': result_id}
        conn.execute('INSERT INTO diagnostic_probes VALUES(?,?,?,?,?,?,?,?)',
                     (pid, paper_id, qids[anchor['question_numbers'][0]], bank_id, skill, encode(payload), 'awaiting_response', stamp()))
        for gid, goal in selected:
            conn.execute('INSERT INTO probe_goals VALUES(?,?)', (pid, gid))
        if explicit:
            conn.execute('INSERT INTO practice_plan_members VALUES(?,?)', (result_id, pid))
    if linked:
        for goal in result['goals']:
            for pid in goal['related_probe_ids']:
                old=conn.execute('''SELECT d.*,p.archived_at FROM diagnostic_probes d
                    JOIN papers p ON p.id=d.paper_id WHERE d.id=?
                    AND d.id NOT IN (SELECT probe_id FROM retired_probes)''',(pid,)).fetchone()
                if not old or old['archived_at']:
                    raise ValueError('引用的历史练习不存在、已停用或来源卷已归档')
                if old['paper_id']==paper_id:
                    raise ValueError('本卷练习请用retained_exercises，不应伪装成跨卷引用')
                state=practice_state(conn,old['paper_id'])
                if not state['is_current'] or pid not in state['probe_ids']:
                    raise ValueError('历史练习所属分析已变化，暂不能作为可继续的复用题；请先复核来源卷')
                require_access(conn,old['bank_id'],internal=True)
                require_bank_read(conn,data,task,old['bank_id'],probe_id=pid)
                conn.execute('INSERT INTO goal_related_probes VALUES(?,?)',(goals[goal['id']][0],pid))
            attached=any(goal['id'] in e['goal_ids'] for e in result['exercises']+retained) or bool(goal['related_probe_ids'])
            if goal['decision']=='practice' and not attached:
                raise ValueError('安排练习的目标须关联实际新增/保留练习或可继续的历史练习')
            if goal['decision']=='no_candidate' and attached:
                raise ValueError('已有可用练习的目标应标practice或monitor，不能同时声称无候选')
    if inputs.get('contract_version')=='1.9':
        review=inputs['practice_knowledge']['legacy_review']
        kept={item['probe_id'] for item in retained}
        deferred={item['probe_id']:item['reason'] for item in previous.get('deferred_probes',[])}
        prior=set(previous.get('probe_ids',[])) if previous.get('result_id') else {p['id'] for p in inputs['probes']}
        prior.update(deferred)
        deferred.update({pid:reason for pid,reason in review.items()
                         if pid in prior})
        retired={r[0] for r in conn.execute('SELECT probe_id FROM retired_probes')}
        for pid,reason in deferred.items():
            if pid not in kept and pid not in retired:
                conn.execute('INSERT INTO practice_deferred_probes VALUES(?,?,?)',(result_id,pid,reason))
    return {'goals': len(result['goals']), 'exercises': len(result['exercises']), 'retained': len(retained)}


def require_bank_read(conn,data,task,bank_id,*,probe_id=None):
    inputs=json.loads(task['input_json'])
    if task['kind']=='prepare_practice' and inputs.get('contract_version')=='1.9':
        if probe_id:
            from app.learning.practice_knowledge import require_existing_read
            require_existing_read(conn,data,task,probe_id)
            return
        from app.bank.annotations import materials
        for role,item in materials(conn,data,bank_id).items():
            require_read(conn,task,'prepared_bank',bank_id,role,item['sha256'])
        return
    bank=conn.execute('SELECT * FROM bank_resources WHERE bank_id=?',(bank_id,)).fetchone()
    if not bank:raise ValueError('练习题资源不存在')
    if not bank['question_path']:
        from app.bank.annotations import materials
        for role,item in materials(conn,data,bank_id).items():
            require_read(conn,task,'bank',bank_id,role,item['sha256'])
        return
    for role in ('question','analysis'):
        if bank[role+'_path']:
            from app.storage.boundaries import material_path
            sha=resource_digest(material_path(data,bank[role+'_path']),data)
            require_read(conn,task,'bank',bank_id,role,sha)


def finish_task(conn, task_id):
    task = task_record(conn, task_id)
    saved = receipt(conn, task_id)
    if not saved or task['result_id'] != saved['result_id']:
        raise ValueError('Agent已结束但本任务结果未成功保存')
    conn.execute("UPDATE learning_tasks SET status='completed',updated_at=? WHERE id=?", (stamp(), task_id))
    if task['kind']=='annotate_questions':
        from app.storage.boundaries import table_exists
        if table_exists(conn,'annotation_provenance'):
            from app.storage.provenance import publish_provenance
            publish_provenance(conn,task['result_id'])
    return saved


def task_package(conn, task_id):
    task = task_record(conn, task_id)
    inputs=json.loads(task['input_json'])
    if task['kind']=='review_practice':
        scope=inputs['practice_review']
        return {**{k:task[k] for k in ('id','kind','paper_id','attempt_id','input_revision','status')},
                'result_schema':result_schema(task['kind'],inputs['contract_version']),'receipt':receipt(conn,task_id),
                'practice_review':{'request':scope['request'],'catalog_revision':scope['catalog_revision'],
                    'entries':[{'probe_id':e['probe']['id'],'bank_id':e['probe']['bank_id'],
                        'available_roles':e['available_roles'],'unavailable_references':e['unavailable_references'],
                        'topic_ids':e['topic_ids']} for e in scope['entries']]},
                'reading':'task_context(probe_ids)读冻结原解答与字段授权；read_bank传probe_id、bank_id、role=all读固定版本；task_context(topic_ids)读规范定义。只修本次允许字段，不改布置范围或学生作答，不另建练习。'}
    if task['kind'] in PREPARATION_KINDS:
        package = {k: task[k] for k in ('id','kind','paper_id','attempt_id','input_revision','status')}
        package.update(input={k: inputs[k] for k in ('task_scope','catalog_revision','rule_revision')},
                       result_schema=result_schema(task['kind'], inputs['contract_version']), receipt=receipt(conn,task_id))
        package['reading'] = '用task_context读取本任务来源或考点定义；实际题干/解析用read_bank，不读取学生画像或作答。'
        if task['kind'] == 'maintain_catalog':
            package['source_manifest'] = [{k:e[k] for k in ('source_id','content_sha256')} for e in inputs['source_entries']]
            package['outline'] = [{k:n[k] for k in ('id','parent_id','name','kind')} for n in inputs['catalog_base']['nodes'] if n['kind'] != 'atom']
        else:
            package['questions'] = [{k:q[k] for k in ('bank_id','content_revision','material_revision','entity_id')} |
                                    {'available_roles':list(q['materials']),
                                     'available_context':[key for key in ('revision_base','reusable_analysis','definition_review_draft') if key in q]}
                                    for q in inputs['bank_questions']]
            package['reading'] += ' 题目清单available_context列出可复用草稿；用task_context传bank_ids读取固定草稿或修订基线，不能代替实际材料/定义阅读。'
        return package
    # The full snapshot is kept for optimistic concurrency, not repeated into
    # model context. Read actual questions/resources using the existing tools.
    brief={k:inputs[k] for k in ('paper','source_sha256','attempt_id','prior_results') if k in inputs}
    if not brief['paper'].get('score_confirmed_at'):
        brief['paper']={**brief['paper'],'score':None}
    brief['known_question_numbers']=[q['number'] for q in inputs.get('questions',[])]
    package = {k: task[k] for k in ('id', 'kind', 'paper_id', 'attempt_id', 'input_revision', 'status')} | {
        'input': brief, 'result_schema': result_schema(task['kind'],inputs.get('contract_version','1.0')),
        'receipt': receipt(conn, task_id)}
    if inputs.get('contract_version')=='2.0' and task['kind'] in ('analyze_paper','review_question'):
        from app.learning.paper_knowledge import manifest
        package['paper_references']=manifest(inputs)
    if task['kind']=='organize_knowledge':
        package['knowledge_catalog']=[{k:n[k] for k in ('id','parent_id','name','aliases')} for n in inputs['knowledge_catalog']]
        from app.knowledge.index import reference_policy
        package['catalog_policy']=reference_policy()
        from app.knowledge.outline import REFERENCE
        package['knowledge_reference']=REFERENCE
        package['source_manifest']=[{k:s[k] for k in ('source_id','source_revision','kind','paper_id')} for s in inputs['knowledge_sources']]
        if inputs.get('contract_version') == '1.8':
            from app.knowledge.source_hints import for_sources
            hints = for_sources(conn, inputs, inputs['knowledge_sources'])
            if hints:
                package['source_topic_hints'] = hints
        package['reading']='用task_context({source_ids:[真实ID]})每次读取1–8份证据；只归纳知识关联，不重新批改或更改原始评价。'
        if inputs.get('contract_version')=='1.8':
            package.update(catalog_revision=inputs['knowledge_catalog_revision'],
                           rule_revision=inputs['knowledge_rule_revision'],scope=inputs['knowledge_request'])
            package['reading']+=' 用knowledge_query定位，再用topic_ids读取本任务捕获定义；只读目录摘要不算核对。'
    if task['kind']=='grade_attempt' and inputs.get('contract_version')=='1.9':
        scope=inputs['grading_knowledge']
        package['grading_knowledge']={k:scope[k] for k in
            ('binding','available_roles','unavailable_references','catalog_revision')}
        package['grading_knowledge']['reading']='read_attempt读作答；read_bank自动使用当时固定版本，可role=all；task_context(topic_ids)核对所引捕获定义。'
    if task['kind'] == 'review_question':
        package['question_review'] = inputs['question_review']
    if task['kind']=='summarize_paper':
        package['allowed_source_refs']=[{'kind':kind,'id':row['id']}
            for kind,key in (('question','questions'),('report','reports'),('attempt','attempts'),('result','prior_results'))
            for row in inputs.get(key,[])]
    if task['kind']=='prepare_practice' and inputs.get('contract_version') in ('1.3','1.4','1.5','1.6','1.9'):
        if inputs.get('contract_version')=='1.9':
            scope=inputs['practice_knowledge']
            package['practice_knowledge']={'catalog_revision':scope['catalog_revision'],
                'mapping_rule_revision':scope['mapping_rule_revision'],
                'question_mappings':scope['question_mappings'],
                'reading':'原卷映射已核；用task_context(knowledge_query/topic_ids)读取捕获定义，再catalog(topic_ids)做就绪召回。'}
        previous = inputs['practice_plan']['state']
        retired = set(inputs['practice_plan']['retired_probe_ids'])
        package['practice_mode'] = 'append' if previous['is_current'] else 'select'
        package['required_retained_probe_ids'] = previous['probe_ids'] if previous['is_current'] else []
        review=inputs.get('practice_knowledge',{}).get('legacy_review',{})
        if review:
            package['required_retained_probe_ids']=[pid for pid in package['required_retained_probe_ids'] if pid not in review]
            package['legacy_review']=[{'probe_id':p['id'],'bank_id':p['bank_id'],'reason':review[p['id']]}
                                      for p in inputs['probes'] if p['id'] in review]
            package['legacy_policy']='无法证明原版本的旧题由系统保留为待核历史，不必放进本轮retained_exercises，也不要求学生修订；不要复制同题。'
        package['existing_exercises'] = [
            {'probe_id': p['id'], 'bank_id': p['bank_id'], 'status': p['status'],
             'current': previous['is_current'] and p['id'] in previous['probe_ids'],
             'attempt_ids': [a['id'] for a in inputs['attempts'] if a['probe_id']==p['id']],
             'purpose': json.loads(p['payload_json']).get('skill_label', ''),
             'question_id': p['question_id']}
            for p in inputs['probes'] if p['id'] not in retired]
        package['existing_goals'] = [json.loads(g['payload_json']) for g in inputs['practice_plan']['goals']]
        if inputs.get('contract_version') in ('1.5','1.6','1.9'):
            states={p['paper_id']:p for p in inputs['other_plans']}
            package['historical_exercises']=[{'probe_id':p['id'],'paper_id':p['paper_id'],
                'question_id':p['question_id'],'bank_id':p['bank_id'],'status':p['status'],
                'purpose':json.loads(p['payload_json']).get('skill_label',''),
                'response_scope':json.loads(p['payload_json']).get('prompt',''),
                'can_reuse':not p['archived_at'] and p['id'] not in retired and
                  states.get(p['paper_id'],{}).get('is_current',False) and
                  p['id'] in states.get(p['paper_id'],{}).get('probe_ids',[])}
                for p in inputs['other_exercises']]
    return package


def retry_task(conn, root, data, task_id):
    with atomic(conn):
        task = task_record(conn, task_id)
        inputs=json.loads(task['input_json'])
        # A saved result changed its own projections, including its parent
        # report. Only an unsaved task needs a fresh input capture here.
        if not task['result_id']:
            current = capture_input(conn, root, data, task['kind'], task['paper_id'], task['attempt_id'],
                                    contract_version=inputs.get('contract_version','1.0'),
                                    review_request=inputs.get('question_review',inputs.get('practice_review',{})).get('request'),task_scope=inputs.get('task_scope'),
                                knowledge_request=inputs.get('knowledge_request'),
                                annotation_rule_revision=inputs.get('rule_revision') if task['kind']=='annotate_questions' else None)
            if 'contract_version' in inputs:current['contract_version']=inputs['contract_version']
            if task['kind']=='organize_knowledge' and inputs.get('contract_version')=='1.8':
                ignored={'knowledge_catalog','knowledge_catalog_revision','knowledge_rule_revision'}
                changed=digest({k:v for k,v in current.items() if k not in ignored})!=digest({k:v for k,v in inputs.items() if k not in ignored})
                from app.knowledge.mapping_versions import RULE_REVISION
                changed=changed or inputs['knowledge_rule_revision']!=RULE_REVISION
            elif task['kind']=='review_practice':
                from app.learning.practice_review import validate_input
                validate_input(conn,inputs,current);changed=False
            elif inputs.get('contract_version')=='2.0' and task['kind'] in ('analyze_paper','review_question'):
                ordinary=lambda value:{k:v for k,v in value.items() if k!='paper_knowledge'}
                changed=digest(ordinary(current))!=digest(ordinary(inputs))
            else:changed=digest(current)!=task['input_revision']
            if changed:
                raise ValueError('原任务输入已改变，请按当前材料重新启动任务')
        token = uuid.uuid4().hex
        conn.execute("UPDATE learning_tasks SET run_token=?,turn_id=NULL,status='queued',error=NULL,updated_at=? WHERE id=?",
                     (token, stamp(), task_id))
        conn.execute('''INSERT INTO task_reads SELECT task_id,?,kind,record_id,role,sha256
                        FROM task_reads WHERE task_id=? AND run_token=?''', (token, task_id, task['run_token']))
    return task_record(conn, task_id)


def rekey_task(conn,task_id,old_token):
    """Invalidate tickets from a released transport without changing its turn."""
    with atomic(conn):
        task=task_record(conn,task_id)
        if task['run_token']!=old_token:raise ValueError('执行身份已由其他连接更新')
        token=uuid.uuid4().hex
        conn.execute('UPDATE learning_tasks SET run_token=?,updated_at=? WHERE id=?',(token,stamp(),task_id))
        conn.execute('''INSERT INTO task_reads SELECT task_id,?,kind,record_id,role,sha256
                        FROM task_reads WHERE task_id=? AND run_token=?''',(token,task_id,old_token))
    return token


def fail_task(conn, task_id, error, status='failed'):
    if status not in ('failed', 'interrupted', 'abandoned'):
        raise ValueError('任务终止状态不合法')
    conn.execute('UPDATE learning_tasks SET status=?,error=?,updated_at=? WHERE id=?',
                 (status, str(error)[:2000], stamp(), task_id))


def task_listing(conn, paper_id=None):
    query = 'SELECT id,workflow_id,kind,paper_id,attempt_id,status,result_id,error,created_at,updated_at FROM learning_tasks'
    return rows(conn, query + (' WHERE paper_id=?' if paper_id else '') + ' ORDER BY created_at,id', (paper_id,) if paper_id else ())
