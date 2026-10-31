"""Reusable mathematical review evidence without session IDs or task inputs."""
import json
from app.knowledge.catalog import digest
from app.storage.boundaries import table_exists


def capture_provenance(conn, annotation):
    row = conn.execute('''SELECT t.input_json,t.run_token,t.id,t.status,r.payload_json,r.payload_sha256
        FROM learning_results r JOIN learning_tasks t ON t.id=r.task_id
        WHERE r.id=? AND r.kind='annotate_questions' ''',(annotation['result_id'],)).fetchone()
    if not row or row['status'] != 'completed':return None
    inputs = json.loads(row['input_json'])
    source = next((q for q in inputs.get('bank_questions',[]) if q['bank_id']==annotation['bank_id']),None)
    analysis = json.loads(annotation['payload_json'])
    if not source or analysis not in json.loads(row['payload_json'])['result']['questions']:return None
    reads = {}
    for role,item in source['materials'].items():
        read = conn.execute('''SELECT sha256 FROM task_reads WHERE task_id=? AND run_token=?
            AND kind='bank_preparation' AND record_id=? AND role=?''',
            (row['id'],row['run_token'],source['bank_id'],role)).fetchone()
        if not read or read[0]!=item['sha256']:return None
        reads[role]=read[0]
    return {'published':True,'rule_revision':inputs['rule_revision'],'source':{k:source[k] for k in ('bank_id','entity_id','content_revision','material_revision','identity','materials')},
            'analysis_sha256':digest(analysis),'reviewed_roles':reads,
            'result_sha256':row['payload_sha256']}


def reviewed_source(conn, annotation):
    if not table_exists(conn,'annotation_provenance'):return None
    row = conn.execute('SELECT payload_json FROM annotation_provenance WHERE annotation_id=?',(annotation['id'],)).fetchone()
    if not row:return None
    value = json.loads(row[0])
    if not value.get('published'):return None
    analysis=json.loads(annotation['payload_json']) if 'payload_json' in annotation.keys() else annotation['analysis']
    if value['analysis_sha256']!=digest(analysis):
        raise ValueError('Shared mathematical review evidence does not match the annotation')
    return value


def save_provenance(conn, task, inputs, result_id):
    for annotation in conn.execute('SELECT * FROM question_annotations WHERE result_id=?',(result_id,)).fetchall():
        source = next(q for q in inputs['bank_questions'] if q['bank_id']==annotation['bank_id'])
        # Only mathematical material/identity fields are shared; execution data stays private.
        clean = {key:source[key] for key in ('bank_id','entity_id','content_revision','material_revision','identity','materials')}
        value = {'published':False,'rule_revision':inputs['rule_revision'],'source':clean,
                 'analysis_sha256':digest(json.loads(annotation['payload_json'])),
                 'reviewed_roles':{role:item['sha256'] for role,item in source['materials'].items()},
                 'result_sha256':conn.execute('SELECT payload_sha256 FROM learning_results WHERE id=?',(result_id,)).fetchone()[0]}
        conn.execute('INSERT INTO annotation_provenance VALUES(?,?)',(annotation['id'],json.dumps(value,ensure_ascii=False,sort_keys=True)))
