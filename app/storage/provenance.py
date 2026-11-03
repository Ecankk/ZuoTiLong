"""Self-contained mathematical review evidence, without execution credentials."""
import json,re
from app.knowledge import catalog
from app.storage.boundaries import table_exists

SCHEMA='mathlens.annotation-proof/v2'
SOURCE_FIELDS=('bank_id','entity_id','content_revision','material_revision','identity','materials')


def evidence_digest(value):
    return catalog.digest({k:v for k,v in value.items() if k!='evidence_sha256'})


def _analysis(annotation):
    return json.loads(annotation['payload_json']) if 'payload_json' in annotation.keys() else annotation['analysis']


def validate_proof(annotation, value, *, published=True):
    """Validate stored public evidence, without querying an execution workspace."""
    try:
        if type(value['published']) is not bool:raise ValueError('通用标注出处发布状态不正确')
        if published and not value['published']:return None
        analysis=_analysis(annotation);source=value['source']
        if (value['analysis_sha256']!=catalog.digest(analysis)
                or value['rule_revision']!=annotation['rule_revision']
                or source['content_revision']!=annotation['content_revision']
                or source['material_revision']!=annotation['material_revision']
                or source['material_revision']!=catalog.digest(source['materials'])
                or source['materials']['question']['sha256']!=source['content_revision']
                or value['reviewed_roles']!={r:m['sha256'] for r,m in source['materials'].items()}):
            raise ValueError('通用标注出处与标注/材料版本不一致')
        origin=annotation['source_bank_id'] if 'source_bank_id' in annotation.keys() else annotation['bank_id']
        if (source['bank_id']!=origin or source['identity'].get(origin)!=source['content_revision']
                or source['entity_id']!=annotation['entity_id']
                or ('identity_json' in annotation.keys() and source['identity']!=json.loads(annotation['identity_json']))):
            raise ValueError('通用标注出处题目身份不一致')
        for material in source['materials'].values():
            if material['sha256']!=catalog.digest(dict(text=material['text'],image_sha256=material['image_sha256'])):
                raise ValueError('通用标注材料内容散列不一致')
        if value.get('schema') is None:return value  # Explicit legacy v1 transition.
        if value['schema']!=SCHEMA or value['evidence_sha256']!=evidence_digest(value):
            raise ValueError('通用标注出处格式或散列不一致')
        summary=value['input_summary']
        if (summary['kind']!='annotate_questions' or summary['catalog_revision']!=annotation['catalog_revision']
                or summary['rule_revision']!=annotation['rule_revision']
                or source['bank_id'] not in summary['bank_ids']
                or any(not isinstance(value.get(k),str) or not re.fullmatch('[0-9a-f]{64}',value[k]) for k in ('input_revision','result_sha256'))
                or value['completion']['status']!=('completed' if value['published'] else 'pending')):
            raise ValueError('通用标注出处输入/完成声明不一致')
        expected=[dict(kind='bank_preparation',record_id=source['bank_id'],role=role,sha256=item['sha256'])
                  for role,item in sorted(source['materials'].items())]
        if value['material_reads']!=expected:raise ValueError('通用标注材料阅读证据不完整')
        bindings={b['topic_id'] for b in analysis['bindings']};seen=set();read_ids=set()
        for read in value['definition_reads']:
            if (read['kind']!='knowledge_definition' or read['role']!=summary['catalog_revision']
                    or read['record_id']!=read['definition']['id']
                    or read['sha256']!=catalog.digest(read['definition'])
                    or read['record_id'] in read_ids or not read['binding_ids']
                    or seen.intersection(read['binding_ids'])):
                raise ValueError('通用标注定义阅读证据不一致')
            seen.update(read['binding_ids']);read_ids.add(read['record_id'])
        if seen!=bindings:raise ValueError('通用标注定义阅读未覆盖引用原子')
        return value
    except (KeyError,TypeError,AttributeError) as exc:
        raise ValueError('通用标注出处字段缺失或类型不正确') from exc


def capture_provenance(conn, annotation, *, published=True):
    """Capture only verified actual rows from the source execution transaction."""
    row=conn.execute('''SELECT t.input_json,t.input_revision,t.run_token,t.id,t.status,t.kind,
        t.result_id AS task_result_id,r.payload_json,r.payload_sha256,r.created_at
        FROM learning_results r JOIN learning_tasks t ON t.id=r.task_id
        WHERE r.id=? AND r.kind='annotate_questions' ''',(annotation['result_id'],)).fetchone()
    if not row or (published and (row['status']!='completed' or row['task_result_id']!=annotation['result_id'])):
        raise ValueError('标注缺少已完成的原交付')
    inputs=json.loads(row['input_json']);envelope=json.loads(row['payload_json']);analysis=_analysis(annotation)
    if (row['kind']!='annotate_questions' or catalog.digest(inputs)!=row['input_revision']
            or catalog.digest(envelope)!=row['payload_sha256']
            or envelope['task_id']!=row['id'] or envelope['kind']!='annotate_questions'
            or envelope['input_revision']!=row['input_revision'] or envelope['paper_id'] is not None
            or analysis not in envelope['result']['questions']):
        raise ValueError('标注原输入/交付散列或范围不一致')
    source=next((q for q in inputs.get('bank_questions',[]) if q['bank_id']==annotation['bank_id']),None)
    if not source:raise ValueError('标注原输入缺少本题')
    from app.bank.annotation_revisions import validate
    validate(source,analysis)
    material_reads=[]
    for role,item in sorted(source['materials'].items()):
        read=conn.execute('''SELECT kind,record_id,role,sha256 FROM task_reads WHERE task_id=? AND run_token=?
            AND kind='bank_preparation' AND record_id=? AND role=?''',(row['id'],row['run_token'],source['bank_id'],role)).fetchone()
        if not read or read['sha256']!=item['sha256']:raise ValueError('标注原材料阅读凭据缺失或不一致')
        material_reads.append(dict(read))
    release=catalog.document(conn,inputs['catalog_revision']);nodes={n['id']:n for n in release['document']['nodes']}
    references={}
    for binding in analysis['bindings']:
        tid=catalog.resolve(conn,binding['topic_id'],inputs['catalog_revision'])
        if tid not in nodes:raise ValueError('标注原定义版本缺失')
        references.setdefault(tid,[]).append(binding['topic_id'])
    definitions=[]
    for tid,ids in sorted(references.items()):
        read=conn.execute('''SELECT kind,record_id,role,sha256 FROM task_reads WHERE task_id=? AND run_token=?
            AND kind='knowledge_definition' AND record_id=? AND role=?''',(row['id'],row['run_token'],tid,inputs['catalog_revision'])).fetchone()
        if not read or read['sha256']!=catalog.digest(nodes[tid]):raise ValueError('标注原定义阅读凭据缺失或不一致')
        definitions.append(dict(read,definition=nodes[tid],binding_ids=sorted(ids)))
    summary=dict(kind='annotate_questions',contract_version=inputs['contract_version'],
        catalog_revision=inputs['catalog_revision'],rule_revision=inputs['rule_revision'],
        bank_ids=sorted(inputs['task_scope']['bank_ids']))
    if source.get('revision_base'):
        base=source['revision_base']
        summary['revision_base']={k:base[k] for k in ('annotation_id','source_bank_id','allowed_fields')}
        summary['revision_base'].update(analysis_sha256=catalog.digest(base['analysis']),resolve_review=base.get('resolve_review',False))
    value=dict(schema=SCHEMA,published=published,rule_revision=inputs['rule_revision'],
        source={k:source[k] for k in SOURCE_FIELDS},analysis_sha256=catalog.digest(analysis),
        reviewed_roles={r:m['sha256'] for r,m in source['materials'].items()},result_sha256=row['payload_sha256'],
        input_revision=row['input_revision'],input_summary=summary,material_reads=material_reads,definition_reads=definitions,
        completion=dict(status='completed' if published else 'pending',delivered_at=row['created_at']))
    value['evidence_sha256']=evidence_digest(value)
    validate_proof(annotation,value,published=False)
    return value


def reviewed_source(conn, annotation):
    if not table_exists(conn,'annotation_provenance'):return None
    row=conn.execute('SELECT payload_json FROM annotation_provenance WHERE annotation_id=?',(annotation['id'],)).fetchone()
    if not row:return None
    value=json.loads(row[0])
    if 'identity_json' not in annotation.keys():
        original=conn.execute('SELECT * FROM question_annotations WHERE id=?',(annotation['id'],)).fetchone()
        if not original or _analysis(original)!=_analysis(annotation):raise ValueError('通用标注内容与保存版本不一致')
        annotation=original
    return validate_proof(annotation,value)


def save_provenance(conn, task, inputs, result_id):
    for annotation in conn.execute('SELECT * FROM question_annotations WHERE result_id=?',(result_id,)).fetchall():
        value=capture_provenance(conn,annotation,published=False)
        conn.execute('INSERT INTO annotation_provenance VALUES(?,?)',(annotation['id'],catalog.encode(value)))


def publish_provenance(conn, result_id):
    for annotation in conn.execute('SELECT * FROM question_annotations WHERE result_id=?',(result_id,)).fetchall():
        value=capture_provenance(conn,annotation)
        conn.execute('UPDATE annotation_provenance SET payload_json=? WHERE annotation_id=?',(catalog.encode(value),annotation['id']))
