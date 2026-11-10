"""Append-only Agent mappings from versioned evidence to stable concepts.

This module never guesses knowledge from strings and never regrades an answer.
Mappings become inactive when their source changes; original records survive.
"""
from app.storage.boundaries import table_exists
import hashlib
import json
from app.knowledge.outline import seeds, REFERENCE, VERSION
from app.learning.legacy_profile import build_profile as legacy_profile, material_revision, parsed


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def revision(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def initialize(conn):
    from app.knowledge.catalog import initialize as initialize_catalog
    initialize_catalog(conn)
    for sql in (
        '''CREATE TABLE IF NOT EXISTS knowledge_nodes(
        id TEXT PRIMARY KEY,parent_id TEXT REFERENCES knowledge_nodes(id),name TEXT NOT NULL,
        aliases_json TEXT NOT NULL,origin_json TEXT NOT NULL,created_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS knowledge_mappings(
        result_id TEXT NOT NULL REFERENCES learning_results(id),source_id TEXT NOT NULL,
        source_revision TEXT NOT NULL,paper_id TEXT NOT NULL REFERENCES papers(id),
        payload_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(result_id,source_id))''',
        '''CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge_mappings(source_id,source_revision)''',
    ):
        conn.execute(sql)
    from app.knowledge.mapping_versions import initialize as initialize_versions
    initialize_versions(conn)
    for nid, parent, label in seeds():
        conn.execute('INSERT OR IGNORE INTO knowledge_nodes VALUES(?,?,?,?,?,?)',
                     (nid, parent, label, '[]', encode(REFERENCE), '2026-10-26'))


def catalog(conn):
    from app.knowledge.catalog import document
    current = document(conn)
    if current:
        return [{'id': n['id'], 'parent_id': n['parent_id'], 'name': n['name'], 'aliases': n['aliases'],
                 'origin': {'catalog_revision': current['id'], 'node_kind': n['kind'],
                            'definition': n['definition'], 'conditions': n['conditions'],
                            'boundaries': n['boundaries'], 'math_types': n['math_types'],
                            'source_refs': n['source_refs'], 'review_note': n['review_note']}}
                for n in current['document']['nodes']]
    if not table_exists(conn, 'knowledge_nodes'):
        return []
    return [{'id':r['id'],'parent_id':r['parent_id'],'name':r['name'],
             'aliases':parsed(r['aliases_json'],[]),'origin':parsed(r['origin_json'],{})}
            for r in conn.execute('SELECT * FROM knowledge_nodes ORDER BY id')]


def reference_policy():
    return {'mode':'reference_existing_only','new_nodes_allowed':False,
            'unmatched':'在limitations描述缺口；仅关联有依据的已有节点，不能生成新的稳定ID。'}


def _scope_level(node, seed_ids):
    kind = node.get('origin', {}).get('node_kind')
    if kind in ('subject', 'chapter', 'topic'):
        return kind
    if kind == 'atom':
        return 'concept'
    # Legacy catalogues predate node_kind; preserve their recorded semantics.
    return 'subject' if not node['parent_id'] else 'chapter' if node['id'] in seed_ids else 'concept'


def compact_catalog(conn):
    return [{k:n[k] for k in ('id','parent_id','name','aliases')} for n in catalog(conn)]


def sources(conn, paper_id=None):
    """Authoritative current snapshots, independent of existing index mappings."""
    raw = legacy_profile(conn,temporal=False)
    events = {e['id']: e for item in raw for e in item['events']}
    output = []
    def add(sid, kind, pid, content, evidence):
        if paper_id and pid != paper_id:
            return
        fields=('id','paper_id','question_id','probe_id','attempt_id','skill_id','label','kind',
                'created_at','source','independent','verified','verified_by_report_id',
                'observation','material_revision','assessment_result_id','detail')
        value = {'source_id': sid, 'kind': kind, 'paper_id': pid, 'content': content,
                 'events': sorted(({k:e[k] for k in fields if k in e} for e in evidence), key=lambda e: e['id'])}
        value['source_revision'] = revision(value)
        output.append(value)
    for row in conn.execute('''SELECT q.id,q.paper_id,q.number,d.report_id,d.diagnosis_json
        FROM questions q JOIN question_diagnoses d ON d.question_id=q.id
        JOIN papers p ON p.id=q.paper_id WHERE p.archived_at IS NULL ORDER BY q.id'''):
        diagnosis=parsed(row['diagnosis_json'], {})
        # Index the saved mathematical scope and observations. The original
        # report remains the source; do not resend its complete worked solution.
        brief={k:diagnosis[k] for k in ('stem','knowledge','fingerprint','correctness','observation',
            'correct_parts','first_error','skill_events','cause_summary') if k in diagnosis}
        add(row['id'], 'question', row['paper_id'],
            {'question_id': row['id'], 'number': row['number'], 'report_id': row['report_id'],
             'diagnosis': brief},
            [e for e in events.values() if e['source']=='exam' and e['question_id']==row['id']])
    from app.learning.plans import practice_state
    states = {}
    for row in conn.execute('''SELECT d.* FROM diagnostic_probes d JOIN papers p ON p.id=d.paper_id
        WHERE p.archived_at IS NULL AND d.id NOT IN (SELECT probe_id FROM retired_probes) ORDER BY d.id'''):
        pid = row['paper_id']
        state = states.setdefault(pid, practice_state(conn, pid))
        add(row['id'], 'probe', pid, {'probe_id': row['id'], 'question_id': row['question_id'],
             'bank_id': row['bank_id'], 'assignment': parsed(row['payload_json'], {}),
             'can_continue': state['is_current'] and row['id'] in state['probe_ids']}, [])
    history = {}
    for row in conn.execute("SELECT record_id,payload FROM record_versions WHERE kind='attempt' ORDER BY created_at,rowid"):
        history.setdefault(row['record_id'], []).append(parsed(row['payload'], {}))
    for row in conn.execute('''SELECT a.*,d.paper_id,d.question_id FROM probe_attempts a
        JOIN diagnostic_probes d ON d.id=a.probe_id JOIN papers p ON p.id=d.paper_id
        WHERE p.archived_at IS NULL ORDER BY a.id'''):
        work = {material_revision(v): v for v in history.get(row['id'], [])+[dict(row)] if isinstance(v,dict)}
        for e in events.values():
            if e['source']!='attempt' or e['attempt_id']!=row['id']:
                continue
            version = work.get(e['material_revision'], {})
            add(e['id'], 'attempt', row['paper_id'], {
                'attempt_id': row['id'], 'probe_id': row['probe_id'], 'question_id': row['question_id'],
                'response': version.get('response',''), 'image_roles': parsed(version.get('image_roles_json'),{}),
                'assessment': parsed(version.get('assessment_json'),{}),
                'material_revision': e['material_revision'], 'independent': e['independent']}, [e])
    return sorted(output, key=lambda s: s['source_id'])


def saved_mappings(conn):
    if not table_exists(conn, 'knowledge_mappings'):
        return {}
    values = {}
    for row in conn.execute('SELECT * FROM knowledge_mappings ORDER BY created_at,rowid'):
        values[(row['source_id'],row['source_revision'])] = parsed(row['payload_json'], {})
    return values


def pending_sources(conn, paper_id=None):
    saved = saved_mappings(conn)
    return [s for s in sources(conn,paper_id) if (s['source_id'],s['source_revision']) not in saved]


def save(conn, result_id, inputs, result):
    from app.learning.loop import stamp
    if result['new_nodes']:
        raise ValueError('统一知识目录只能由独立目录维护流程修改；普通知识整理必须复用已有ID，new_nodes应为空，未匹配内容记入limitations')
    available = {s['source_id']:s for s in inputs['knowledge_sources']}
    incoming = result['mappings']
    if len({m['source_id'] for m in incoming}) != len(incoming) or {m['source_id'] for m in incoming} != set(available):
        raise ValueError('知识整理必须覆盖本任务的全部待整理来源，未知可留空关联，不得遗漏或新增来源')
    versioned=inputs.get('contract_version')=='1.8'
    known = {n['id']:n for n in (inputs['knowledge_catalog'] if versioned else catalog(conn))}
    if versioned:
        from app.knowledge.mapping_versions import validate_current
        validate_current(conn,inputs,result)
    for mapping in incoming:
        source = available[mapping['source_id']]
        if mapping['source_revision'] != source['source_revision']:
            raise ValueError('知识映射引用了过期的题目或作答版本')
        if not set(mapping['topic_ids']).issubset(known):
            raise ValueError('知识映射引用了不存在的稳定考点')
        events = {e['id'] for e in source['events']}
        links = mapping['event_topics']
        if len({e['event_id'] for e in links})!=len(links) or {e['event_id'] for e in links}!=events:
            raise ValueError('每条原始表现证据须明确关联或保留未知，不得遗漏、重复或伪造评价')
        for link in links:
            if not set(link['topic_ids']).issubset(mapping['topic_ids']):
                raise ValueError('表现证据不能扩散到本题未关联的考点')
            if len(link['topic_ids'])>1:
                raise ValueError('一条概括性的表现只归入一个最有依据的考点；其他关联保留为覆盖信息')
        conn.execute('INSERT INTO knowledge_mappings VALUES(?,?,?,?,?,?)',
            (result_id,mapping['source_id'],source['source_revision'],source['paper_id'],encode(mapping),stamp()))
        if versioned:
            from app.knowledge.mapping_versions import metadata
            conn.execute('INSERT INTO knowledge_mapping_versions VALUES(?,?,?)',
                         (result_id,mapping['source_id'],encode(metadata(inputs,mapping))))
    return {'mapped_sources':len(incoming),'new_nodes':len(result['new_nodes'])}


def snapshot(conn):
    nodes = catalog(conn)
    from app.knowledge.catalog import resolve
    maintained = next((n['origin'].get('catalog_revision') for n in nodes
                       if n['origin'].get('catalog_revision')), None)
    canonical = (lambda node_id: resolve(conn, node_id, maintained)) if maintained else (lambda node_id: node_id)
    seed_ids={nid for nid,_,_ in seeds()}
    from app.knowledge.mapping_versions import latest
    states=latest(conn,nodes)
    saved = {key:item['mapping'] for key,item in states.items()
             if item['status'] in ('current','legacy_unversioned')}
    current = sources(conn)
    grouped = {n['id']:{'skill_id':n['id'],'label':n['name'],'parent_id':n['parent_id'],
        'scope_level':_scope_level(n,seed_ids),
        'aliases':n['aliases'],'previous_ids':[],'origin':n['origin'],'events':[],'probe_ids':[],
        'question_ids':[],'hypotheses':[],'scopes':[]} for n in nodes}
    # Navigation metadata belongs to the read-only profile projection. Keep it
    # out of catalog() and frozen learning-task inputs/definition digests.
    if maintained:
        for row in conn.execute('SELECT old_id,target_id FROM knowledge_catalog_redirects WHERE release_id=? ORDER BY old_id', (maintained,)):
            if row['old_id'] not in grouped and row['target_id'] in grouped:
                grouped[row['target_id']]['previous_ids'].append(row['old_id'])
    pending = [];outdated=[]
    for source in current:
        key=(source['source_id'],source['source_revision'])
        mapping = saved.get(key)
        status=states.get(key,{}).get('status','unmapped')
        if status!='current':
            outdated.append({'source_id':source['source_id'],'paper_id':source['paper_id'],
                             'kind':source['kind'],'reason':status})
            if mapping is not None:
                pending.append({'source_id':source['source_id'],'paper_id':source['paper_id'],
                                'kind':source['kind'],'reason':status})
        if mapping is None:
            pending.append({'source_id':source['source_id'],'paper_id':source['paper_id'],
                            'kind':source['kind'],'reason':status})
            continue
        for tid in {canonical(t) for t in mapping['topic_ids']}:
            if tid not in grouped:
                continue
            item=grouped[tid];content=source['content']
            item['scopes'].append({'source_id':source['source_id'],'paper_id':source['paper_id'],
                                  'reason':mapping['reason'],'mapping_status':status})
            if source['kind']=='question':item['question_ids'].append(content['question_id'])
            if source['kind']=='probe' and content.get('can_continue'):item['probe_ids'].append(content['probe_id'])
        for binding in mapping['event_topics']:
            event = next(e for e in source['events'] if e['id']==binding['event_id'])
            for tid in {canonical(t) for t in binding['topic_ids']}:
                if tid in grouped:
                    grouped[tid]['events'].append(event)
    from app.learning.free_practice import topic_events
    for tid,event in topic_events(conn):
        tid=canonical(tid)
        if tid in grouped:grouped[tid]['events'].append(event)
    from app.learning.profile_practice import topic_events as profile_events
    from app.storage.boundaries import table_exists
    if table_exists(conn,'profile_practice_attempts'):
        for tid,event in profile_events(conn):
            tid=canonical(tid)
            if tid in grouped:grouped[tid]['events'].append(event)
    from app.knowledge.profile import aggregate
    for item in grouped.values():
        from app.learning.dates import project
        item['events']=project(conn,item['events'])
        aggregate(item)
        if any(s['mapping_status']=='legacy_unversioned' for s in item['scopes']):
            item['state_reason']+=' 包含尚未按当前目录/规则核验的历史映射，需整理后再作细考点判断。'
    return {'nodes':list(grouped.values()),'pending_sources':pending,
            'outdated_sources':outdated,'reference':REFERENCE}
