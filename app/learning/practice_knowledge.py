"""Prepared-question admission and immutable references for learning plans.

Programmatic recall establishes provenance; the Agent still judges mathematical
fit. A source alias shares question knowledge, not an unverified material hash.
"""
import json
from app.learning.tasks import task_inputs
from app.bank import annotations
from app.knowledge import catalog,index,mapping_versions
from app.storage import annotation_cache as annotation_origins

CONTRACT_VERSION='1.9'


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS practice_question_bindings(
        result_id TEXT NOT NULL REFERENCES learning_results(id),
        probe_id TEXT NOT NULL REFERENCES diagnostic_probes(id),
        bank_id TEXT NOT NULL REFERENCES bank_questions(id),
        annotation_id TEXT NOT NULL REFERENCES prepared_annotation_ids(id),
        content_revision TEXT NOT NULL,material_revision TEXT NOT NULL,
        payload_json TEXT NOT NULL,PRIMARY KEY(result_id,probe_id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS practice_deferred_probes(
        result_id TEXT NOT NULL REFERENCES learning_results(id),
        probe_id TEXT NOT NULL REFERENCES diagnostic_probes(id),reason TEXT NOT NULL,
        PRIMARY KEY(result_id,probe_id))''')
    existed=conn.execute("SELECT 1 FROM sqlite_master WHERE name='practice_attempt_materials'").fetchone()
    conn.execute('''CREATE TABLE IF NOT EXISTS practice_attempt_materials(
        attempt_id TEXT PRIMARY KEY REFERENCES probe_attempts(id),
        binding_result_id TEXT,probe_id TEXT NOT NULL REFERENCES diagnostic_probes(id),
        FOREIGN KEY(binding_result_id,probe_id) REFERENCES practice_question_bindings(result_id,probe_id))''')
    if not existed:
        conn.execute('INSERT INTO practice_attempt_materials SELECT id,NULL,probe_id FROM probe_attempts')


def capture(conn,paper_id,data):
    """Capture versions and bounded legacy-image checks, without changing records."""
    release=catalog.active_id(conn)
    if not release:raise ValueError('统一知识目录尚未发布，暂不开始原子选题')
    nodes=index.catalog(conn);saved=mapping_versions.latest(conn,nodes)
    originals=[s for s in index.sources(conn,paper_id) if s['kind']=='question']
    if not originals:raise ValueError('原卷尚无已保存的题目分析')
    mapped=[]
    for source in originals:
        value=saved.get((source['source_id'],source['source_revision']))
        if not value or value['status']!='current':
            raise ValueError('原卷考点映射尚未就绪，请先完成本卷知识整理后选题')
        mapped.append({'source_id':source['source_id'],'source_revision':source['source_revision'],
                       'number':source['content']['number'],'mapping_result_id':value['result_id'],
                       'mapping':value['mapping'],'version':value['version']})
    manifest=annotation_origins.manifest(conn,catalog.digest)
    existing={}
    for row in conn.execute('SELECT * FROM practice_question_bindings ORDER BY rowid'):
        existing.setdefault(row['probe_id'],catalog.digest(dict(row)))
    legacy={};review={}
    for row in conn.execute('SELECT * FROM diagnostic_probes ORDER BY id'):
        if row['id'] not in existing:
            proof=legacy_origin(conn,dict(row));legacy[row['id']]=proof
            if not proof:
                review[row['id']]='原选题题图阅读凭据缺失，原记录保留，暂未纳入本轮训练。'
            else:
                try:question=annotations.materials(conn,data,row['bank_id'])['question']
                except ValueError:review[row['id']]='旧练习原题材料缺失，原记录与作答保留。'
                else:
                    if question['image_sha256']!=proof['question_image_sha256']:
                        review[row['id']]='当前题图与原选题版本不一致，原记录与作答保留。'
    return {'catalog_revision':release,'catalog_nodes':nodes,'question_mappings':mapped,
            'mapping_rule_revision':mapping_versions.RULE_REVISION,'annotation_manifest':manifest,
            'existing_bindings':existing,'legacy_origins':legacy,'legacy_review':review}


def material_binding(conn,data,bank_id,annotation):
    actual=annotations.materials(conn,data,bank_id)
    from app.bank.figures import markers as figure_markers
    return {'bank_id':bank_id,'annotation_id':annotation['id'],**({'supplemental_figures':figure_markers(conn,bank_id)} if figure_markers(conn,bank_id) else {}),
            'content_revision':actual['question']['sha256'],
            'material_revision':catalog.digest(actual),
            'annotation_content_revision':annotation['content_revision'],
            'annotation_material_revision':annotation['material_revision'],
            'annotation_rule_revision':annotation['rule_revision'],
            'annotation_catalog_revision':annotation['catalog_revision'],
            'source_bank_id':annotation['source_bank_id']}


def recalled(conn,data,task,lease,bank_id,annotation_id):
    """Called by the prepared-atom tool, never by coarse source navigation."""
    inputs=task_inputs(conn,task);scope=inputs['practice_knowledge']
    annotation=annotations.current(conn,data,bank_id)
    if not annotation or annotation['analysis']['status']!='ready' or annotation['id']!=annotation_id:
        raise ValueError('召回题目标注不是当前就绪版本')
    row=annotation_origins.record(conn,annotation_id)
    if scope['annotation_manifest'].get(annotation_id)!=catalog.digest(dict(row)):
        raise ValueError('题目标注不属于本任务捕获版本，须重新准备选题任务')
    value=material_binding(conn,data,bank_id,annotation)
    from app.learning.tasks import record_read
    record_read(conn,lease,'prepared_recall',bank_id,annotation_id,catalog.digest(value))
    return value


def require_binding(conn,data,task,bank_id,annotation_id):
    inputs=task_inputs(conn,task);scope=inputs['practice_knowledge']
    annotation=annotations.current(conn,data,bank_id)
    if not annotation or annotation['analysis']['status']!='ready' or annotation['id']!=annotation_id:
        raise ValueError('新补强题须使用当前有效ready标注，不能回退粗标签或未标注题')
    row=annotation_origins.record(conn,annotation_id)
    if scope['annotation_manifest'].get(annotation_id)!=catalog.digest(dict(row)):
        raise ValueError('选题引用了任务外或已变化的标注版本')
    binding=material_binding(conn,data,bank_id,annotation)
    from app.learning.tasks import require_read
    require_read(conn,task,'prepared_recall',bank_id,annotation_id,catalog.digest(binding))
    return binding


def require_topics(conn,task,inputs,result):
    """Knowledge membership/reading is structural; teaching fit stays human/AI."""
    scope=inputs['practice_knowledge'];nodes=scope['catalog_nodes'];known={n['id']:n for n in nodes}
    ids={topic for goal in result['goals'] for topic in goal['topic_ids']}
    if not ids.issubset(known):raise ValueError('选题目标引用了目录外考点ID')
    from app.learning.tasks import require_read
    for topic in ids:
        require_read(conn,task,'practice_definition',topic,scope['catalog_revision'],catalog.digest(known[topic]))
    require_current_definitions(conn,nodes,ids)


def require_current_definitions(conn,nodes,ids):
    # Reviewed redirects can preserve a definition; changed mathematical
    # conditions or ancestry require a fresh task with current evidence.
    expected=mapping_versions.dependencies(nodes,ids)
    current_nodes=index.catalog(conn)
    resolved={topic:catalog.resolve(conn,topic) for topic in expected}
    current=mapping_versions.dependencies(current_nodes,resolved.values())
    if set(current)!=set(resolved.values()) or any(current.get(resolved[topic])!=sha for topic,sha in expected.items()):
        raise ValueError('选题所引定义或层级已变化，请先更新映射再选题')


def legacy_origin(conn,probe):
    """SQL evidence of the image read by the original successful selector."""
    import uuid
    payload=json.loads(probe['payload_json'])
    result=conn.execute('''SELECT r.*,t.run_token FROM learning_results r JOIN learning_tasks t ON t.id=r.task_id
        WHERE r.id=? AND r.kind='prepare_practice' AND r.paper_id=?''',
        (payload.get('source_result_id'),probe['paper_id'])).fetchone()
    if not result:return None
    value=json.loads(result['payload_json'])
    selected=next((e for e in value['result']['exercises'] if e['bank_id']==probe['bank_id']
        and 'probe-'+uuid.uuid5(uuid.NAMESPACE_URL,result['id']+':'+e['id']).hex==probe['id']),None)
    if not selected:return None
    read=conn.execute('''SELECT sha256 FROM task_reads WHERE task_id=? AND run_token=?
        AND kind='bank' AND record_id=? AND role='question' ''',
        (result['task_id'],result['run_token'],probe['bank_id'])).fetchone()
    if not read:return None
    return {'result_id':result['id'],'task_id':result['task_id'],'bank_id':probe['bank_id'],
            'question_image_sha256':read[0],'selection_sha256':catalog.digest(selected)}


def legacy_binding(conn,data,inputs,probe_id):
    probe=conn.execute('SELECT * FROM diagnostic_probes WHERE id=?',(probe_id,)).fetchone()
    scope=inputs['practice_knowledge'];proof=scope['legacy_origins'].get(probe_id)
    if not probe or not proof or legacy_origin(conn,dict(probe))!=proof:
        raise ValueError('旧练习缺少原选题阅读凭据，保留历史；须先恢复原题版本再复核')
    actual=annotations.materials(conn,data,probe['bank_id'])
    if actual['question']['image_sha256']!=proof['question_image_sha256']:
        raise ValueError('旧练习题图与原任务阅读版本不一致，不能改绑当前题库')
    annotation=annotations.current(conn,data,probe['bank_id'])
    if not annotation or annotation['analysis']['status']!='ready':
        raise ValueError('旧练习原题已确认，但当前通用标注尚未就绪，先完成题目预标注')
    row=annotation_origins.record(conn,annotation['id'])
    if scope['annotation_manifest'].get(annotation['id'])!=catalog.digest(dict(row)):
        raise ValueError('旧练习复核标注不属于当前任务捕获版本')
    from app.storage.practice_materials import freeze
    binding=freeze(conn,data,material_binding(conn,data,probe['bank_id'],annotation))
    binding.update(legacy_origin=proof,probe_id=probe_id,binding_result_id=None)
    return binding,binding['material_manifest']


def require_reviewed_references(conn,annotation,manifest):
    """Prove review of frozen references from the annotation's saved inputs.

    Known v1 original materials remain reusable after v2. A v1 alias whose
    reference differed was never reviewed by that result and cannot inherit
    trust merely because both rules are readable. Use saved inputs rather
    than today's mutable bank, so valid frozen practice survives updates.
    """
    if isinstance(annotation,dict) and annotation.get('cache_provenance'):
        from app.bank.annotation_packages import require_reference_proof
        return require_reference_proof(conn,annotation,manifest)
    if annotation['rule_revision'] not in annotations.SUPPORTED_RULE_REVISIONS:
        raise ValueError('历史练习标注规则不受支持，须先复核')
    from app.storage.provenance import reviewed_source
    proof = reviewed_source(conn, annotation)
    inputs={'rule_revision':proof['rule_revision'],'bank_questions':[proof['source']]} if proof else {}
    source=next((q for q in inputs.get('bank_questions',[]) if q['bank_id']==annotation['bank_id']),None)
    if (not source or inputs.get('rule_revision')!=annotation['rule_revision']
            or source['material_revision']!=annotation['material_revision']
            or catalog.digest(source['materials'])!=annotation['material_revision']
            or source['identity'].get(manifest['bank_id'])!=manifest['content_revision']):
        raise ValueError('历史练习缺少对应标注的原始材料核验依据，须先复核')
    reviewed=annotations.reference_signature(source['materials'])
    selected=annotations.reference_signature(manifest['resources'])
    if not reviewed or reviewed!=selected:
        raise ValueError('历史练习参考版本未获该标注核验，须先复核')


def existing_binding(conn,data,inputs,probe_id):
    """A retained probe keeps its original material and annotation versions."""
    binding=binding_for(conn,probe_id)
    if not binding:return legacy_binding(conn,data,inputs,probe_id)
    scope=inputs['practice_knowledge']
    row=conn.execute('SELECT * FROM practice_question_bindings WHERE result_id=? AND probe_id=?',
                     (binding['binding_result_id'],probe_id)).fetchone()
    if scope['existing_bindings'].get(probe_id)!=catalog.digest(dict(row)):
        raise ValueError('历史练习绑定不是本任务捕获版本')
    annotation=annotation_origins.record(conn,binding['annotation_id'])
    if not annotation or scope['annotation_manifest'].get(annotation['id'])!=catalog.digest(dict(annotation)):
        raise ValueError('历史练习标注不属于本任务捕获版本')
    if (annotation['rule_revision'] not in annotations.SUPPORTED_RULE_REVISIONS
            or json.loads(annotation['payload_json'])['status']!='ready'
            or annotation['content_revision']!=binding['annotation_content_revision']
            or annotation['material_revision']!=binding['annotation_material_revision']):
        raise ValueError('历史练习标注或规则已变化，须先复核')
    old=json.loads(annotation['dependencies_json'])
    current=annotations.concept_dependencies(conn,list(old))
    resolved={topic:catalog.resolve(conn,topic) for topic in old}
    if set(current)!=set(resolved.values()) or any(current.get(resolved[t])!=h for t,h in old.items()):
        raise ValueError('历史练习所引原子定义已变化，须先复核')
    from app.storage.practice_materials import load
    manifest=load(data,binding['snapshot_key'],binding['snapshot_sha256'])
    if (manifest['bank_id']!=binding['bank_id'] or manifest['content_revision']!=binding['content_revision']
            or manifest['material_revision']!=binding['material_revision']):
        raise ValueError('历史练习快照与原绑定不一致')
    require_reviewed_references(conn,annotation,manifest)
    return binding,manifest


def require_existing_read(conn,data,task,probe_id):
    inputs=task_inputs(conn,task)
    binding,manifest=existing_binding(conn,data,inputs,probe_id)
    from app.learning.tasks import require_read
    for role,item in manifest['resources'].items():
        require_read(conn,task,'practice_material',probe_id,role,item['sha256'])
    return binding


def validate_input(conn,task,inputs,current,result):
    """Ignore unrelated directory/index growth, never changed student evidence."""
    def stable(value):
        value=dict(value)
        if task['kind']=='prepare_practice':
            value.pop('bank',None)
            scope=dict(value['practice_knowledge'])
            for key in ('catalog_revision','catalog_nodes','annotation_manifest','existing_bindings','legacy_origins','legacy_review'):scope.pop(key,None)
            value['practice_knowledge']=scope
        else:
            scope=dict(value['grading_knowledge'])
            for key in ('catalog_revision','catalog_nodes'):scope.pop(key,None)
            value['grading_knowledge']=scope
        return value
    if catalog.digest(stable(current))!=catalog.digest(stable(inputs)):
        raise ValueError('任务证据或材料绑定已变化，拒绝覆盖新内容')
    if task['kind']=='prepare_practice':
        if inputs.get('contract_version')!='1.10':require_topics(conn,task,inputs,result)
    else:require_current_definitions(conn,inputs['grading_knowledge']['catalog_nodes'],result['topic_ids'])


def save_new_bindings(conn,data,task,result_id,result):
    inputs=task_inputs(conn,task);require_topics(conn,task,inputs,result)
    for exercise in result['exercises']:
        binding=require_binding(conn,data,task,exercise['bank_id'],exercise['annotation_id'])
        from app.storage.practice_materials import freeze
        binding=freeze(conn,data,binding)
        import uuid
        probe='probe-'+uuid.uuid5(uuid.NAMESPACE_URL,result_id+':'+exercise['id']).hex
        conn.execute('INSERT INTO practice_question_bindings VALUES(?,?,?,?,?,?,?)',
                     (result_id,probe,binding['bank_id'],binding['annotation_id'],binding['content_revision'],
                      binding['material_revision'],json.dumps(binding,ensure_ascii=False,sort_keys=True)))
    reused={item['probe_id'] for item in result['retained_exercises']}
    reused.update(pid for goal in result['goals'] for pid in goal['related_probe_ids'])
    for probe in sorted(reused):
        if binding_for(conn,probe):continue
        binding=require_existing_read(conn,data,task,probe)
        binding={k:v for k,v in binding.items() if k not in ('probe_id','binding_result_id')}
        conn.execute('INSERT INTO practice_question_bindings VALUES(?,?,?,?,?,?,?)',
                     (result_id,probe,binding['bank_id'],binding['annotation_id'],binding['content_revision'],
                      binding['material_revision'],json.dumps(binding,ensure_ascii=False,sort_keys=True)))


def binding_for(conn,probe_id,attempt_id=None):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='practice_question_bindings'").fetchone():return None
    if attempt_id is None:
        row=conn.execute('SELECT * FROM practice_question_bindings WHERE probe_id=? ORDER BY rowid LIMIT 1',(probe_id,)).fetchone()
    else:
        row=conn.execute('''SELECT b.* FROM practice_attempt_materials a JOIN practice_question_bindings b
            ON b.result_id=a.binding_result_id AND b.probe_id=a.probe_id
            WHERE a.attempt_id=? AND a.probe_id=?''',(attempt_id,probe_id)).fetchone()
    if not row:return None
    value=json.loads(row['payload_json'])
    return {**value,'binding_result_id':row['result_id'],'probe_id':probe_id}


def bind_attempt(conn,attempt_id,*,reused=False):
    if conn.execute('SELECT 1 FROM practice_attempt_materials WHERE attempt_id=?',(attempt_id,)).fetchone():return
    attempt=conn.execute('SELECT probe_id FROM probe_attempts WHERE id=?',(attempt_id,)).fetchone()
    if not attempt:raise ValueError('作答不存在')
    # A retried legacy submission cannot retroactively acquire a newer version.
    binding=None if reused else binding_for(conn,attempt['probe_id'])
    conn.execute('INSERT INTO practice_attempt_materials VALUES(?,?,?)',
                 (attempt_id,binding['binding_result_id'] if binding else None,attempt['probe_id']))


def grading_version(conn,attempt_id):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='practice_attempt_materials'").fetchone():return '1.6'
    row=conn.execute('SELECT binding_result_id FROM practice_attempt_materials WHERE attempt_id=?',(attempt_id,)).fetchone()
    return '1.9' if row and row[0] else '1.6'


def grading_contract(conn,attempt_id,requested=None):
    if conn.execute('SELECT 1 FROM profile_practice_attempts WHERE id=?',(attempt_id,)).fetchone():
        if requested not in (None,'1.12'):raise ValueError('画像练习须使用1.12批改契约')
        return '1.12'
    if requested=='1.12':raise ValueError('1.12仅用于画像练习')
    if conn.execute("SELECT 1 FROM free_practice_attempts WHERE id=?",(attempt_id,)).fetchone():
        if requested not in (None,'1.11'):raise ValueError('自由练习须使用1.11批改契约')
        return '1.11'
    if requested=='1.11':raise ValueError('1.11仅用于自由练习')
    current=grading_version(conn,attempt_id)
    if current=='1.9' and requested not in (None,'1.9'):
        raise ValueError('本次作答绑定固定题目版本，必须使用1.9批改契约')
    return requested or current


def capture_grade(conn,data,attempt_id):
    attempt=conn.execute('SELECT probe_id FROM probe_attempts WHERE id=?',(attempt_id,)).fetchone()
    if not attempt:raise ValueError('作答不存在')
    binding=binding_for(conn,attempt['probe_id'],attempt_id)
    if not binding:raise ValueError('旧作答没有固定材料版本，应使用兼容批改契约')
    from app.storage.practice_materials import load
    manifest=load(data,binding['snapshot_key'],binding['snapshot_sha256'],('question',))
    annotation=annotation_origins.record(conn,binding['annotation_id'])
    if not annotation:raise ValueError('练习对应标注缺失，须先恢复原记录')
    require_reviewed_references(conn,annotation,manifest)
    available=['question'];unavailable=[]
    for role in manifest['resources']:
        if role=='question':continue
        try:load(data,binding['snapshot_key'],binding['snapshot_sha256'],(role,));available.append(role)
        except ValueError as error:unavailable.append({'role':role,'reason':str(error)})
    nodes=index.catalog(conn)
    brief={k:v for k,v in binding.items() if k!='material_manifest'}
    return {'binding':brief,'materials':manifest,'available_roles':sorted(available),
            'unavailable_references':unavailable,'catalog_nodes':nodes,
            'catalog_revision':mapping_versions.catalog_revision(nodes)}


def require_grade(conn,task,inputs,result):
    scope=inputs['grading_knowledge'];known={n['id']:n for n in scope['catalog_nodes']}
    if not set(result['topic_ids']).issubset(known):raise ValueError('批改引用了目录外考点ID')
    from app.learning.tasks import require_read
    for topic in result['topic_ids']:
        require_read(conn,task,'grade_definition',topic,scope['catalog_revision'],catalog.digest(known[topic]))
    for role in scope['available_roles']:
        require_read(conn,task,'practice_material',scope['binding']['probe_id'],role,scope['materials']['resources'][role]['sha256'])
