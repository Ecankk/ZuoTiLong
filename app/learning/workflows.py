"""Durable application scheduling; every Codex task still owns one stage.

Queueing is local and does not create a Codex session. Only the bridge, after
reconciling the actual remote turn, may dispatch a queued job. Existing tasks
without a job are never retroactively chained on upgrade.
"""
from __future__ import annotations

from app.storage.paths import paper_path, relative_file, resolve_file, connection_data
import json
import uuid

from app.learning.loop import stamp


PENDING = ('queued', 'dispatching', 'running')


def init_workflows(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS workflow_jobs(
      id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,workflow_id TEXT NOT NULL,
      paper_id TEXT REFERENCES papers(id),kind TEXT NOT NULL,attempt_id TEXT,
      auto_prepare INTEGER NOT NULL DEFAULT 0,guard_json TEXT NOT NULL,
      status TEXT NOT NULL,task_id TEXT REFERENCES learning_tasks(id),error TEXT,
      recovery_required INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
    if 'recovery_required' not in {row[1] for row in conn.execute('PRAGMA table_info(workflow_jobs)')}:
        conn.execute('ALTER TABLE workflow_jobs ADD COLUMN recovery_required INTEGER NOT NULL DEFAULT 0')
    if 'index_after' not in {row[1] for row in conn.execute('PRAGMA table_info(workflow_jobs)')}:
        conn.execute('ALTER TABLE workflow_jobs ADD COLUMN index_after INTEGER NOT NULL DEFAULT 0')
    if 'review_json' not in {row[1] for row in conn.execute('PRAGMA table_info(workflow_jobs)')}:
        conn.execute('ALTER TABLE workflow_jobs ADD COLUMN review_json TEXT')
    if 'scope_json' not in {row[1] for row in conn.execute('PRAGMA table_info(workflow_jobs)')}:
        conn.execute('ALTER TABLE workflow_jobs ADD COLUMN scope_json TEXT')
    columns={r[1] for r in conn.execute('PRAGMA table_info(workflow_jobs)')}
    if 'knowledge_json' not in columns:conn.execute('ALTER TABLE workflow_jobs ADD COLUMN knowledge_json TEXT')
    if 'contract_version' not in columns:conn.execute('ALTER TABLE workflow_jobs ADD COLUMN contract_version TEXT')
    if 'index_contract_version' not in columns:
        conn.execute("ALTER TABLE workflow_jobs ADD COLUMN index_contract_version TEXT NOT NULL DEFAULT '1.6'")
    if 'practice_contract_version' not in columns:
        conn.execute("ALTER TABLE workflow_jobs ADD COLUMN practice_contract_version TEXT NOT NULL DEFAULT '1.6'")
    if 'continue_practice' not in columns:
        conn.execute('ALTER TABLE workflow_jobs ADD COLUMN continue_practice INTEGER NOT NULL DEFAULT 0')
    # Existing waiting jobs retain their old task and continuation semantics.
    conn.execute("UPDATE workflow_jobs SET contract_version=CASE WHEN kind IN ('maintain_catalog','annotate_questions') THEN '1.7' ELSE '1.6' END WHERE contract_version IS NULL")


def guard(conn, root, data, kind, paper_id, attempt_id=None, *, review_request=None, task_scope=None, knowledge_request=None):
    from app.learning.tasks import digest, resource_digest
    from app.knowledge.maintenance import KINDS
    if kind in KINDS:
        if paper_id is not None or attempt_id is not None:raise ValueError('通用知识任务不能关联学生试卷/作答')
        from app.knowledge.maintenance import guard as preparation_guard
        return preparation_guard(conn,data,kind,task_scope)
    if task_scope is not None:raise ValueError('试卷任务不能夹带题库作用域')
    paper = conn.execute('SELECT * FROM papers WHERE id=?', (paper_id,)).fetchone()
    if not paper or paper['archived_at'] or not paper['source_path']:
        raise ValueError('试卷不存在、已归档或缺少原PDF')
    result = {'source_sha256': resource_digest(paper_path(data,paper['source_path'],root), data)}
    if knowledge_request is not None:
        if kind!='organize_knowledge':raise ValueError('只有知识整理可以携带证据范围')
        from app.knowledge.mapping_versions import select_sources,RULE_REVISION
        result.update(knowledge_sources=digest(select_sources(conn,paper_id,knowledge_request)),
                      knowledge_request=knowledge_request,rule_revision=RULE_REVISION)
        return result
    if kind=='review_practice':
        from app.learning.practice_review import capture
        scope=capture(conn,data,paper_id,review_request)
        result['practice_review_sha256']=digest({k:v for k,v in scope.items() if k not in ('catalog_revision','catalog_nodes')})
        return result
    latest = conn.execute('''SELECT id,report_json FROM agent_reports WHERE paper_id=?
                            ORDER BY created_at DESC,rowid DESC LIMIT 1''', (paper_id,)).fetchone()
    result['report_id'] = latest['id'] if latest else None
    if kind == 'review_question':
        from app.learning.question_review import capture_review
        result['review_sha256'] = digest(capture_review(conn, root, data, paper_id, review_request))
    if kind == 'prepare_practice':
        report = json.loads(latest['report_json']) if latest else {}
        if report.get('completion') != 'complete' or report.get('review', {}).get('status') != 'verified':
            raise ValueError('原卷分析尚未完整核对通过，暂不准备练习')
        if report.get('source_sha256') != result['source_sha256']:
            raise ValueError('原PDF已改变，请先重新核对原卷分析')
    if kind == 'grade_attempt':
        attempt = conn.execute('''SELECT a.* FROM probe_attempts a JOIN diagnostic_probes p
          ON p.id=a.probe_id WHERE a.id=? AND p.paper_id=?''', (attempt_id, paper_id)).fetchone()
        if not attempt:
            raise ValueError('作答不属于当前试卷')
        from app.learning.loop import require_active_probe
        require_active_probe(conn,attempt['probe_id'])
        result['attempt_sha256'] = digest(dict(attempt))
        from app.storage.images import image_records, image_path
        result['image_sha256'] = [resource_digest(image_path(image, data), data)
                                 for image in image_records(conn, json.loads(attempt['images_json']))]
    return result


def enqueue(conn, root, data, kind, paper_id, request_id, attempt_id=None, *,
            workflow_id=None, auto_prepare=False, review_request=None, index_after=False, task_scope=None,
            knowledge_request=None, contract_version=None, index_contract_version='1.8',
            practice_contract_version=None, continue_practice=False):
    from app.learning.contracts import KINDS,default_version,result_schema
    from app.learning.tasks import atomic, encode
    if kind not in KINDS or ((kind == 'grade_attempt') != bool(attempt_id)):
        raise ValueError('任务类型或作答标识不合法')
    try:
        request_id = str(uuid.UUID(request_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('任务请求标识无效') from None
    if kind == 'review_question':
        from app.learning.question_review import normalize_request
        review_request = normalize_request(review_request)
    elif kind=='review_practice':
        from app.learning.practice_review import normalize_request
        review_request=normalize_request(review_request)
    elif review_request is not None:
        raise ValueError('只有指定复核任务可以附加复核材料')
    review_json = encode(review_request) if review_request else None
    from app.knowledge.maintenance import KINDS as preparation_kinds, normalize_scope
    if kind in preparation_kinds:
        task_scope = normalize_scope(kind,task_scope)
    elif task_scope is not None:raise ValueError('试卷任务不能携带通用知识作用域')
    scope_json = encode(task_scope) if task_scope is not None else None
    prior_job=conn.execute('SELECT * FROM workflow_jobs WHERE request_id=?',(request_id,)).fetchone()
    version=contract_version or (prior_job['contract_version'] if prior_job else default_version(kind))
    if kind=='grade_attempt':
        from app.learning.practice_knowledge import grading_contract
        version=grading_contract(conn,attempt_id,contract_version or (prior_job['contract_version'] if prior_job else None))
    practice_version=practice_contract_version or (prior_job['practice_contract_version'] if prior_job else '1.6')
    if practice_version not in ('1.6','1.9','1.10'):raise ValueError('后续选题契约版本不合法')
    if type(continue_practice) is not bool or continue_practice and (kind!='organize_knowledge' or version!='1.8' or practice_version not in ('1.9','1.10')):
        raise ValueError('只有1.8前置知识整理可以继续1.9选题')
    result_schema(kind,version);result_schema('organize_knowledge',index_contract_version)
    if knowledge_request is not None and (kind!='organize_knowledge' or version!='1.8'):
        raise ValueError('只有1.8知识整理可以携带证据范围')
    if kind=='organize_knowledge' and version=='1.8':
        from app.knowledge.mapping_versions import normalize_request,select_sources
        if knowledge_request is None and prior_job and prior_job['knowledge_json']:
            knowledge_request=json.loads(prior_job['knowledge_json'])
        if knowledge_request is None:
            knowledge_request={'source_ids':[s['source_id'] for s in select_sources(conn,paper_id)],'refresh':True}
        knowledge_request=normalize_request(knowledge_request)
    knowledge_json=encode(knowledge_request) if knowledge_request is not None else None
    if auto_prepare and kind not in ('analyze_paper', 'review_question'):
        raise ValueError('只有原卷分析可以自动衔接首次选题')
    with atomic(conn):
        existing = conn.execute('SELECT * FROM workflow_jobs WHERE request_id=?', (request_id,)).fetchone()
        if existing:
            if (existing['kind'], existing['paper_id'], existing['attempt_id'], bool(existing['auto_prepare'])) != (
                    kind, paper_id, attempt_id, bool(auto_prepare)):
                raise ValueError('同一请求不能用于其他任务')
            if existing['review_json'] != review_json:
                raise ValueError('同一复核请求不能更换材料')
            if existing['scope_json'] != scope_json:raise ValueError('同一通用知识请求不能更换作用域')
            if existing['knowledge_json']!=knowledge_json:raise ValueError('同一知识整理请求不能更换证据范围')
            if contract_version is not None and existing['contract_version']!=version:
                raise ValueError('同一阶段不能更换契约版本')
            if existing['practice_contract_version']!=practice_version or bool(existing['continue_practice'])!=continue_practice:
                raise ValueError('同一阶段不能更换后续选题策略')
            return dict(existing)
        # A browser retry after losing the HTTP response must also reuse the
        # current pending work when its fresh request UUID differs.
        current_guard = guard(conn, root, data, kind, paper_id, attempt_id, review_request=review_request,task_scope=task_scope,knowledge_request=knowledge_request)
        existing = conn.execute('''SELECT * FROM workflow_jobs WHERE paper_id IS ? AND kind=?
          AND attempt_id IS ? AND review_json IS ? AND scope_json IS ? AND knowledge_json IS ? AND contract_version=?
          AND practice_contract_version=? AND continue_practice=? AND auto_prepare=?
          AND status IN ('queued','dispatching','running') ORDER BY rowid LIMIT 1''',
                                (paper_id, kind, attempt_id, review_json,scope_json,knowledge_json,version,practice_version,int(continue_practice),int(auto_prepare))).fetchone()
        if existing:
            if (kind == 'grade_attempt' and existing['status'] == 'queued' and not existing['task_id']
                    and json.loads(existing['guard_json']) != current_guard):
                mark(conn, existing['id'], 'superseded', '作答已补充，使用新版本的待批改任务')
            else:
                return dict(existing)
        job_id = 'job-' + uuid.uuid5(uuid.NAMESPACE_URL, 'mathlens:job:' + request_id).hex
        now = stamp()
        conn.execute('''INSERT INTO workflow_jobs(id,request_id,workflow_id,paper_id,kind,attempt_id,
          auto_prepare,guard_json,review_json,status,created_at,updated_at,index_after,scope_json,knowledge_json,contract_version,index_contract_version,
          practice_contract_version,continue_practice) VALUES(?,?,?,?,?,?,?,?,?,'queued',?,?,?,?,?,?,?,?,?)''',
          (job_id, request_id, workflow_id or job_id, paper_id, kind, attempt_id,
           int(auto_prepare), encode(current_guard), review_json, now, now, int(index_after),scope_json,knowledge_json,version,index_contract_version,practice_version,int(continue_practice)))
    return dict(conn.execute('SELECT * FROM workflow_jobs WHERE id=?', (job_id,)).fetchone())


def request_practice(conn,root,data,paper_id,request_id,*,workflow_id=None,index_after=True):
    """The user asks once; map missing original evidence in its own turn first."""
    from app.learning.tasks import atomic
    with atomic(conn):
        old=conn.execute('SELECT * FROM workflow_jobs WHERE request_id=?',(request_id,)).fetchone()
        if old:
            if (old['paper_id']!=paper_id or old['practice_contract_version'] not in ('1.9','1.10')
                    or not (old['kind']=='prepare_practice' or old['kind']=='organize_knowledge' and old['continue_practice'])):
                raise ValueError('同一请求不能用于其他任务或选题策略')
            return dict(old)
        guard(conn,root,data,'prepare_practice',paper_id)
        from app.knowledge.mapping_versions import select_sources
        pending=[s['source_id'] for s in select_sources(conn,paper_id) if s['kind']=='question']
        if pending:
            return enqueue(conn,root,data,'organize_knowledge',paper_id,request_id,workflow_id=workflow_id,
                contract_version='1.8',knowledge_request={'source_ids':pending,'refresh':True},
                practice_contract_version='1.10',continue_practice=True,index_after=index_after)
        return enqueue(conn,root,data,'prepare_practice',paper_id,request_id,workflow_id=workflow_id,
            contract_version='1.10',practice_contract_version='1.10',index_after=index_after)


def listing(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_jobs'").fetchone():
        return []
    return [dict(row) for row in conn.execute('''SELECT j.id,j.paper_id,j.kind,j.attempt_id,j.status,
      j.task_id,j.error,j.recovery_required,j.created_at,j.updated_at,p.title AS paper_title
      FROM workflow_jobs j LEFT JOIN papers p ON p.id=j.paper_id
      ORDER BY CASE WHEN j.status IN ('queued','dispatching','running','blocked') THEN 0 ELSE 1 END,
      j.created_at DESC,j.rowid DESC LIMIT 30''')]


def mark(conn, job_id, status, error=None, task_id=None):
    conn.execute('''UPDATE workflow_jobs SET status=?,error=?,task_id=COALESCE(?,task_id),updated_at=?
                    WHERE id=? AND (status IS NOT ? OR error IS NOT ? OR (? IS NOT NULL AND task_id IS NOT ?))''',
                 (status, str(error)[:2000] if error else None, task_id, stamp(), job_id,
                  status, str(error)[:2000] if error else None, task_id, task_id))


def reconcile(conn, root, data):
    """Advance only from committed local completion receipts."""
    from app.learning.tasks import atomic
    with atomic(conn):
        for job in conn.execute("SELECT * FROM workflow_jobs WHERE status IN ('queued','dispatching','running')").fetchall():
            task = conn.execute('SELECT * FROM learning_tasks WHERE request_id=?', (job['request_id'],)).fetchone()
            if not task:
                if job['status'] == 'dispatching':
                    mark(conn, job['id'], 'queued')  # no task or remote send existed
                continue
            if task['status'] == 'completed' and task['result_id']:
                mark(conn, job['id'], 'completed', task_id=task['id'])
                try:
                    continue_job(conn,root,data,dict(job),dict(task))
                except ValueError as exc:
                    mark(conn,job['id'],'blocked','已保存；下一阶段尚未排入：'+str(exc),task_id=task['id'])
            elif task['status'] in ('failed', 'interrupted', 'abandoned'):
                mark(conn, job['id'], task['status'], task['error'], task['id'])
            else:
                mark(conn, job['id'], 'running', task_id=task['id'])


def next_job(conn):
    return conn.execute("SELECT * FROM workflow_jobs WHERE status='queued' AND recovery_required=0 ORDER BY created_at,rowid LIMIT 1").fetchone()


def retry_job(conn, root, data, job_id):
    job = conn.execute('SELECT * FROM workflow_jobs WHERE id=?', (job_id,)).fetchone()
    if not job or job['status'] not in ('blocked', 'failed', 'interrupted'):
        raise ValueError('该阶段无需重新排入')
    if job['task_id'] or job['recovery_required']:
        task=conn.execute('SELECT * FROM learning_tasks WHERE id=?',(job['task_id'],)).fetchone() if job['task_id'] else None
        if task and task['result_id']:
            if task['status']!='completed':
                from app.learning.tasks import finish_task
                finish_task(conn,task['id'])
            continue_job(conn,root,data,dict(job),dict(conn.execute('SELECT * FROM learning_tasks WHERE id=?',(task['id'],)).fetchone()))
            mark(conn,job_id,'completed');return
        mark(conn,job_id,'abandoned','重试使用新的任务与会话，旧执行保留')
        replacement=enqueue(conn,root,data,job['kind'],job['paper_id'],str(uuid.uuid4()),job['attempt_id'],
            workflow_id=job['workflow_id'],auto_prepare=bool(job['auto_prepare']),index_after=bool(job['index_after']),
            review_request=json.loads(job['review_json']) if job['review_json'] else None,
            task_scope=json.loads(job['scope_json']) if job['scope_json'] else None,
            knowledge_request=json.loads(job['knowledge_json']) if job['knowledge_json'] else None,
            contract_version=job['contract_version'],index_contract_version=job['index_contract_version'],
            practice_contract_version=job['practice_contract_version'],continue_practice=bool(job['continue_practice']))
        conn.execute("UPDATE knowledge_preparation_items SET job_id=? WHERE job_id=? AND status='running'",(replacement['id'],job_id))
        return
    from app.learning.tasks import encode
    conn.execute("UPDATE workflow_jobs SET guard_json=?,status='queued',error=NULL,updated_at=? WHERE id=?",
                 (encode(guard(conn, root, data, job['kind'], job['paper_id'], job['attempt_id'],
                               review_request=json.loads(job['review_json']) if job['review_json'] else None,
                               task_scope=json.loads(job['scope_json']) if job['scope_json'] else None,
                               knowledge_request=json.loads(job['knowledge_json']) if job['knowledge_json'] else None)), stamp(), job_id))


def can_cancel(conn,job):
    if not job:return False
    if not job['task_id']:return job['status'] in ('queued','blocked','failed')
    if job['status'] not in ('failed','interrupted'):return False
    task=conn.execute('SELECT status,result_id FROM learning_tasks WHERE id=?',(job['task_id'],)).fetchone()
    if not task or task['status'] not in ('failed','interrupted','abandoned') or task['result_id']:return False
    if conn.execute('SELECT 1 FROM learning_results WHERE task_id=?',(job['task_id'],)).fetchone():return False
    return not conn.execute("SELECT 1 FROM learning_tasks WHERE status IN ('running','repairing','result_saved') LIMIT 1").fetchone()

def cancel_job(conn, job_id):
    from app.learning.tasks import atomic
    with atomic(conn):
        job=conn.execute('SELECT * FROM workflow_jobs WHERE id=?',(job_id,)).fetchone()
        if not can_cancel(conn,job):raise ValueError('只能取消未交付且已终止的阶段；正在执行或已有结果须先核对原任务')
        mark(conn,job_id,'abandoned','用户取消；原卷、作答、任务历史和已保存结果保留')


def continue_job(conn,root,data,job,task):
    """Schedule from a locally validated, committed task result."""
    if task['status']!='completed' or not task['result_id']:
        raise ValueError('原阶段尚未确认完成')
    if task['kind'] in ('maintain_catalog','annotate_questions'):
        from app.knowledge.preparation import advance
        advance(conn,root,data,job,task)
        return
    if job['auto_prepare'] and task['kind'] in ('analyze_paper','review_question'):
        payload=json.loads(conn.execute('SELECT payload_json FROM learning_results WHERE id=?',(task['result_id'],)).fetchone()[0])['result']
        if task['kind']=='review_question':
            from app.learning.semantic_dependencies import signature
            before=json.loads(task['input_json'])['question_review']['question']
            if signature(before)==signature(payload['question']):return
        review=payload['report'].get('review',{}) if task['kind']=='analyze_paper' else payload['review']
        if payload['completion']=='complete' and review.get('status')=='verified':
            request=str(uuid.uuid5(uuid.NAMESPACE_URL,'mathlens:prepare:'+job['id']))
            if job.get('practice_contract_version','1.6') in ('1.9','1.10'):
                request_practice(conn,root,data,job['paper_id'],request,workflow_id=job['workflow_id'],
                                 index_after=bool(job.get('index_after')))
            else:
                enqueue(conn,root,data,'prepare_practice',job['paper_id'],request,
                        workflow_id=job['workflow_id'],index_after=bool(job.get('index_after')),
                        contract_version=job.get('practice_contract_version','1.6'),
                        index_contract_version=job.get('index_contract_version','1.6'))
    elif task['kind']=='organize_knowledge' and job.get('continue_practice'):
        request=str(uuid.uuid5(uuid.NAMESPACE_URL,'mathlens:prepared-after-mapping:'+job['id']))
        enqueue(conn,root,data,'prepare_practice',job['paper_id'],request,workflow_id=job['workflow_id'],
                contract_version=job['practice_contract_version'],practice_contract_version=job['practice_contract_version'],
                index_after=bool(job['index_after']),index_contract_version='1.8')
    elif job.get('index_after') and task['kind'] in ('prepare_practice','grade_attempt'):
        from app.knowledge.index import pending_sources
        index_version=job.get('index_contract_version','1.6')
        if index_version=='1.8':
            from app.knowledge.mapping_versions import select_sources
            pending=select_sources(conn,job['paper_id'])
        else:pending=pending_sources(conn,job['paper_id'])
        if pending:
            request=str(uuid.uuid5(uuid.NAMESPACE_URL,'mathlens:knowledge:'+job['id']))
            enqueue(conn,root,data,'organize_knowledge',job['paper_id'],request,workflow_id=job['workflow_id'],
                    contract_version=index_version)
