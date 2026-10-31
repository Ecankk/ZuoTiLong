"""Durable batches for catalogue curation and reusable bank analyses."""
import json
import uuid
from app.knowledge import catalog


def initialize(conn):
    for sql in (
        '''CREATE TABLE IF NOT EXISTS knowledge_preparation_runs(
        id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,
        source_version_id TEXT,scope_json TEXT NOT NULL,status TEXT NOT NULL,
        auto_annotate INTEGER NOT NULL,batch_size INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS knowledge_preparation_items(
        run_id TEXT NOT NULL REFERENCES knowledge_preparation_runs(id),item_id TEXT NOT NULL,
        status TEXT NOT NULL,job_id TEXT REFERENCES workflow_jobs(id),note TEXT,
        PRIMARY KEY(run_id,item_id))''',
    ):
        conn.execute(sql)


def snapshot(conn, run_id=None):
    query = 'SELECT * FROM knowledge_preparation_runs'
    rows = conn.execute(query + (' WHERE id=?' if run_id else ' ORDER BY rowid DESC LIMIT 20'), (run_id,) if run_id else ())
    result = []
    for row in rows:
        item = dict(row)
        item.pop('scope_json')
        item['counts'] = {r['status']: r['n'] for r in conn.execute(
            'SELECT status,count(*) n FROM knowledge_preparation_items WHERE run_id=? GROUP BY status', (row['id'],))}
        item['total'] = sum(item['counts'].values())
        item['issues'] = [dict(r) for r in conn.execute('''SELECT item_id,status,note FROM knowledge_preparation_items
            WHERE run_id=? AND status='needs_review' ORDER BY rowid LIMIT 30''', (row['id'],))]
        item['jobs'] = [dict(r) for r in conn.execute('''SELECT DISTINCT j.id,j.kind,j.status,j.error FROM workflow_jobs j
            JOIN knowledge_preparation_items i ON i.job_id=j.id WHERE i.run_id=? AND i.status='running' ''', (row['id'],))]
        result.append(item)
    return {'runs': result, 'catalog_revision': catalog.active_id(conn)}


def start(conn, root, data, *, kind, request_id, source_version_id=None, item_ids=None, auto_annotate=False, batch_size=None):
    if kind not in ('catalog','questions'):raise ValueError('未知资料准备类型')
    try:request_id = str(uuid.UUID(request_id))
    except (ValueError,TypeError,AttributeError):raise ValueError('资料准备请求标识无效') from None
    size = batch_size if batch_size is not None else (24 if kind=='catalog' else 4)
    if type(size) is not int or not 1 <= size <= (40 if kind=='catalog' else 8):raise ValueError('资料准备批次大小不合法')
    if type(auto_annotate) is not bool or kind!='catalog' and auto_annotate:raise ValueError('自动接题目标注仅用于完整目录批次')
    if kind=='catalog':
        available = [r[0] for r in conn.execute("SELECT id FROM knowledge_source_entries WHERE source_version_id=? AND kind='atom' ORDER BY rowid", (source_version_id,))]
        if not available:raise ValueError('没有可维护的固定原子来源')
    else:
        if not catalog.active_id(conn):raise ValueError('请先发布统一目录')
        available = [r[0] for r in conn.execute("SELECT id FROM bank_questions WHERE source!='本地示例题库' ORDER BY id")]
    ids = item_ids if item_ids is not None else available
    if not isinstance(ids,list) or not ids or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids) or not set(ids).issubset(available):
        raise ValueError('资料准备范围为空、重复或含未知条目')
    if auto_annotate and set(ids)!=set(available):raise ValueError('目录小样不能自动触发全库标注，请完成完整目录批次后继续')
    scope = {'item_ids':ids,'source_version_id':source_version_id,'kind':kind,'auto_annotate':auto_annotate,'batch_size':size}
    old = conn.execute('SELECT * FROM knowledge_preparation_runs WHERE request_id=?',(request_id,)).fetchone()
    if old:
        if json.loads(old['scope_json'])!=scope:raise ValueError('同一准备请求不能更换范围')
        return snapshot(conn,old['id'])
    from app.learning.loop import stamp
    rid = 'preparation-' + uuid.uuid5(uuid.NAMESPACE_URL,'mathlens:preparation:'+request_id).hex
    with catalog.atomic(conn):
        conn.execute('INSERT INTO knowledge_preparation_runs VALUES(?,?,?,?,?,?,?,?,?,?)',
                     (rid,request_id,kind,source_version_id,catalog.encode(scope),'running',int(auto_annotate),size,stamp(),stamp()))
        for item_id in ids:
            conn.execute("INSERT INTO knowledge_preparation_items VALUES(?,?,'queued',NULL,NULL)",(rid,item_id))
        schedule(conn,root,data,rid)
    return snapshot(conn,rid)


def schedule(conn,root,data,run_id):
    while _schedule_once(conn,root,data,run_id):
        pass


def catalog_scope(conn,source_version_id,source_ids):
    scope={'source_version_id':source_version_id,'source_ids':source_ids}
    metadata=json.loads(conn.execute('SELECT metadata_json FROM knowledge_source_versions WHERE id=?',(source_version_id,)).fetchone()[0])
    if metadata.get('evidence_root'):
        refs=set()
        for sid in source_ids:
            entry=json.loads(conn.execute('SELECT payload_json FROM knowledge_source_entries WHERE source_version_id=? AND id=?',(source_version_id,sid)).fetchone()[0])
            refs.update(ref['id'] for ref in entry['record'].get('references',[]))
        if refs:scope['reference_ids']=sorted(refs)
    return scope


def _schedule_once(conn,root,data,run_id):
    run = conn.execute('SELECT * FROM knowledge_preparation_runs WHERE id=?',(run_id,)).fetchone()
    if not run or run['status']!='running':return
    if conn.execute("SELECT 1 FROM knowledge_preparation_items WHERE run_id=? AND status='running'",(run_id,)).fetchone():return
    if run['kind']=='questions':
        from app.bank.annotations import current
        reusable = conn.execute('''SELECT DISTINCT i.item_id FROM knowledge_preparation_items i JOIN question_annotation_links l
            ON l.bank_id=i.item_id WHERE i.run_id=? AND i.status IN ('queued','needs_review') ''',(run_id,)).fetchall()
        from app.storage.annotation_cache import exists as cache_exists
        if cache_exists(conn):
            reused_ids = {r[0] for r in reusable}
            reusable += [r for r in conn.execute('''SELECT DISTINCT i.item_id FROM knowledge_preparation_items i
                JOIN imported_question_annotations a ON a.bank_id=i.item_id
                WHERE i.run_id=? AND i.status IN ('queued','needs_review')''', (run_id,)) if r[0] not in reused_ids]
        for row in reusable:
            try:item = current(conn,data,row['item_id'])
            except ValueError:item = None
            if item and item['analysis']['status']=='ready':
                conn.execute("UPDATE knowledge_preparation_items SET status='completed',note='复用当前有效通用标注' WHERE run_id=? AND item_id=?",(run_id,row['item_id']))
    else:
        current = catalog.document(conn)
        resolved = {(r['source_version_id'],r['source_id']):r for r in current['document']['source_resolutions']} if current else {}
        for row in conn.execute("SELECT item_id FROM knowledge_preparation_items WHERE run_id=? AND status IN ('queued','needs_review')",(run_id,)).fetchall():
            saved = resolved.get((run['source_version_id'],row['item_id']))
            if saved and saved['disposition']!='pending':
                conn.execute("UPDATE knowledge_preparation_items SET status='completed',note=? WHERE run_id=? AND item_id=?",
                             ('复用已处置来源：'+current['id'],run_id,row['item_id']))
    queued = [r[0] for r in conn.execute("SELECT item_id FROM knowledge_preparation_items WHERE run_id=? AND status='queued' ORDER BY rowid",(run_id,))]
    if not queued:
        from app.learning.loop import stamp
        issues = conn.execute("SELECT 1 FROM knowledge_preparation_items WHERE run_id=? AND status='needs_review'",(run_id,)).fetchone()
        conn.execute('UPDATE knowledge_preparation_runs SET status=?,updated_at=? WHERE id=?',('needs_review' if issues else 'completed',stamp(),run_id))
        if run['kind']=='catalog' and run['auto_annotate'] and conn.execute("SELECT 1 FROM bank_questions WHERE source!='本地示例题库'").fetchone():
            request = str(uuid.uuid5(uuid.NAMESPACE_URL,'mathlens:annotations-after:'+run_id))
            start(conn,root,data,kind='questions',request_id=request)
        return
    if run['kind']=='catalog':
        chapters={row['id']:json.loads(row['payload_json'])['chapter_key'] for row in conn.execute(
            'SELECT id,payload_json FROM knowledge_source_entries WHERE source_version_id=?',(run['source_version_id'],))}
        chapter=chapters[queued[0]]
        batch = [sid for sid in queued if chapters[sid]==chapter][:run['batch_size']]
        scope = catalog_scope(conn,run['source_version_id'],batch);kind='maintain_catalog'
        # Only newly scheduled batches gain this gate. Existing queued/task
        # snapshots keep their captured scope and result contract.
    else:
        batch = queued[:run['batch_size']];scope={'bank_ids':batch};kind='annotate_questions'
    from app.learning.workflows import enqueue
    generation = conn.execute('SELECT count(*) FROM workflow_jobs WHERE workflow_id=?',(run_id,)).fetchone()[0]
    request = str(uuid.uuid5(uuid.NAMESPACE_URL,'mathlens:batch:'+run_id+':'+catalog.digest(batch)+':'+str(generation)))
    try:
        job = enqueue(conn,root,data,kind,None,request,workflow_id=run_id,task_scope=scope)
    except ValueError as exc:
        if len(batch)>1:
            # Isolate the concrete unreadable item instead of losing a whole
            # library. Each singleton is validated before marking its issue.
            from app.knowledge.maintenance import guard
            bad=[]
            for item_id in batch:
                single = {'bank_ids':[item_id]} if kind=='annotate_questions' else catalog_scope(conn,run['source_version_id'],[item_id])
                try:guard(conn,data,kind,single)
                except ValueError as error:bad.append((item_id,str(error)))
            if not bad:raise
            for item_id,error in bad:conn.execute("UPDATE knowledge_preparation_items SET status='needs_review',note=? WHERE run_id=? AND item_id=?",(error,run_id,item_id))
        else:
            conn.execute("UPDATE knowledge_preparation_items SET status='needs_review',note=? WHERE run_id=? AND item_id=?",(str(exc),run_id,batch[0]))
        return True
    for item_id in batch:
        conn.execute("UPDATE knowledge_preparation_items SET status='running',job_id=? WHERE run_id=? AND item_id=?",(job['id'],run_id,item_id))


def advance(conn,root,data,job,task):
    run = conn.execute('SELECT * FROM knowledge_preparation_runs WHERE id=?',(job['workflow_id'],)).fetchone()
    if not run:return
    if task['status']!='completed' or not task['result_id']:raise ValueError('资料批次尚未确认完成')
    payload = json.loads(conn.execute('SELECT payload_json FROM learning_results WHERE id=?',(task['result_id'],)).fetchone()[0])['result']
    inputs = json.loads(task['input_json'])
    if task['kind']=='maintain_catalog':
        outcomes = {r['source_id']:('needs_review' if r['disposition']=='pending' else 'completed',r['reason']) for r in payload['source_resolutions']}
    else:
        outcomes={}
        for question in payload['questions']:
            source=next(q for q in inputs['bank_questions'] if q['bank_id']==question['bank_id'])
            for bid in source['identity']:
                outcomes[bid]=('completed' if question['status']=='ready' else 'needs_review','；'.join(question['limitations']+question['unmatched_topics']))
    for item_id,(status,note) in outcomes.items():
        conn.execute("UPDATE knowledge_preparation_items SET status=?,note=? WHERE run_id=? AND item_id=? AND job_id=? AND status='running'",
                     (status,note,run['id'],item_id,job['id']))
    if run['status']=='pausing':
        conn.execute("UPDATE knowledge_preparation_runs SET status='paused' WHERE id=?",(run['id'],))
    schedule(conn,root,data,run['id'])


def action(conn,root,data,run_id,operation):
    run=conn.execute('SELECT * FROM knowledge_preparation_runs WHERE id=?',(run_id,)).fetchone()
    if not run:raise ValueError('资料准备批次不存在')
    if operation=='pause':
        if run['status'] not in ('running','pausing','paused'):raise ValueError('该批资料准备没有在运行')
        active=False
        jobs=conn.execute('''SELECT DISTINCT j.* FROM workflow_jobs j JOIN knowledge_preparation_items i ON i.job_id=j.id
            WHERE i.run_id=? AND i.status='running' ''',(run_id,)).fetchall()
        from app.learning.workflows import mark
        for job in jobs:
            if job['status'] in ('queued','blocked') and not job['task_id']:
                mark(conn,job['id'],'abandoned','资料准备暂停；来源与已保存标注保留')
                conn.execute("UPDATE knowledge_preparation_items SET status='queued',job_id=NULL WHERE run_id=? AND job_id=?",(run_id,job['id']))
            else:
                active=True
        conn.execute('UPDATE knowledge_preparation_runs SET status=? WHERE id=?',('pausing' if active else 'paused',run_id))
    elif operation=='resume':
        if run['status'] not in ('paused','pausing'):raise ValueError('该批资料准备无需继续')
        if run['kind']=='questions':
            from app.bank.annotations import current
            for row in conn.execute("SELECT item_id FROM knowledge_preparation_items WHERE run_id=? AND status='completed'",(run_id,)).fetchall():
                try:annotation=current(conn,data,row['item_id'])
                except ValueError:annotation=None
                if not annotation or annotation['analysis']['status']!='ready':
                    conn.execute("UPDATE knowledge_preparation_items SET status='queued',job_id=NULL,note='恢复时原标注已失效，按当前材料重新核对' WHERE run_id=? AND item_id=?",(run_id,row['item_id']))
        conn.execute("UPDATE knowledge_preparation_runs SET status='running' WHERE id=?",(run_id,))
        schedule(conn,root,data,run_id)
    else:raise ValueError('资料准备仅支持暂停或继续')
    return snapshot(conn,run_id)
