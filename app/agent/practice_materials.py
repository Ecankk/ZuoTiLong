"""Read the selected exercise version through the existing read_bank tool."""
import json
from app.bank.access import access,require_access
from app.learning.practice_knowledge import binding_for
from app.storage.practice_materials import load,image_path


def _live_candidate(conn,data,task,lease,payload,image_content):
    from app.bank import annotations
    from app.learning.tasks import record_read
    bank_id=payload['bank_id'];state=require_access(conn,bank_id,internal=True)
    actual=annotations.materials(conn,data,bank_id);role=payload.get('role','question')
    if role not in ('all',*actual):raise ValueError('题目没有对应材料或角色不合法')
    roles=list(actual) if role=='all' else [role]
    images=[];resources=[]
    for current in roles:
        item=actual[current];position=None
        if item['path']:
            from app.storage.boundaries import material_path
            images.append(image_content(material_path(data,item['path']),data));position=len(images)
        resources.append({'role':current,'text':item['text'],'image_index':position,'sha256':item['sha256']})
        record_read(conn,lease,'prepared_bank',bank_id,current,item['sha256'])
    result={'bank_id':bank_id,'resources':resources,'student_access':state,'internal_only':True,
            'instruction':'内部核对当前实际题目版本；student_access只控制学生网页展示，隐藏不限制Agent内部阅读或选题。读过不等于已就绪，未标注或冲突项不能加入新补强池，预留与历史规则仍须遵守。'}
    annotation=annotations.current(conn,data,bank_id)
    inputs=json.loads(task['input_json'])
    if annotation and annotation['analysis']['status']=='ready' and annotation['id'] in inputs['practice_knowledge']['annotation_manifest']:
        from app.learning.practice_knowledge import material_binding
        result['prepared_question']=annotations.prepared_summary(annotation)
        result['prepared_question'].update(internal_only=True,material_binding=material_binding(conn,data,bank_id,annotation),
            reading=result['prepared_question'].get('reading','可复用已核通用解法；实际材料和训练目的仍需核对。同题不代表所有来源的解析均已核，不提前显示答案。'))
    result['agent_access']={'can_read':True,'student_mask_limits_agent':False,
                            'ready_in_task_snapshot':'prepared_question' in result}
    return [{'type':'text','text':json.dumps(result,ensure_ascii=False)},*images]


def read(conn,data,task,lease,payload,image_content):
    if not task:return None
    inputs=json.loads(task['input_json'])
    if inputs.get('contract_version') not in ('1.9','2.1'):return None
    reviewing=task['kind']=='review_practice'
    grading=task['kind']=='grade_attempt' or reviewing
    if reviewing:
        entries=inputs['practice_review']['entries']
        candidates=[e for e in entries if e['probe']['bank_id']==payload['bank_id'] and payload.get('probe_id') in (None,e['probe']['id'])]
        if len(candidates)!=1:raise ValueError('解答复核须明确本范围的probe_id和bank_id')
        scope=candidates[0];binding=scope['binding']
    elif grading:
        scope=inputs['grading_knowledge'];binding=scope['binding']
        if payload.get('probe_id') not in (None,binding['probe_id']):raise ValueError('读取的练习不是本次作答')
        if payload['bank_id']!=binding['bank_id']:raise ValueError('批改须读取本次作答的固定题目版本')
    elif task['kind']=='prepare_practice' and payload.get('probe_id'):
        probe=conn.execute('SELECT bank_id FROM diagnostic_probes WHERE id=?',(payload['probe_id'],)).fetchone()
        if not probe or probe['bank_id']!=payload['bank_id']:raise ValueError('练习与题库来源不一致')
        from app.learning.practice_knowledge import existing_binding
        binding,_=existing_binding(conn,data,inputs,payload['probe_id'])
        scope=None
    elif task['kind']=='prepare_practice':return _live_candidate(conn,data,task,lease,payload,image_content)
    else:return None
    role=payload.get('role','question')
    if role not in ('all','question','analysis','answer'):raise ValueError('练习材料角色不合法')
    # Reservation excludes new selection. It must not prevent grading an
    # already submitted answer to a previously assigned version.
    state=access(conn,binding['bank_id']) if grading else require_access(conn,binding['bank_id'],internal=True)
    manifest=load(data,binding['snapshot_key'],binding['snapshot_sha256'],('question',))
    if manifest['bank_id']!=binding['bank_id'] or manifest['content_revision']!=binding['content_revision']:
        raise ValueError('固定练习材料与作答来源不一致')
    requested=(scope['available_roles'] if grading else list(manifest['resources'])) if role=='all' else [role]
    if grading and any(r not in scope['available_roles'] for r in requested):
        raise ValueError('对应参考快照不可读；可按已保存题干独立核验，勿要求学生转录参考答案')
    images=[];resources=[]
    from app.learning.tasks import record_read
    for current in requested:
        checked=load(data,binding['snapshot_key'],binding['snapshot_sha256'],(current,))
        item=checked['resources'].get(current)
        if not item:raise ValueError('本练习版本没有该类材料')
        position=None
        if item['image_file']:
            images.append(image_content(image_path(data,binding,current),data));position=len(images)
        resources.append({'role':current,'text':item['text'],'image_index':position,'sha256':item['sha256']})
        record_read(conn,lease,'practice_material',binding['probe_id'],current,item['sha256'])
    brief={k:v for k,v in binding.items() if k!='material_manifest'}
    result={'bank_id':binding['bank_id'],'probe_id':binding['probe_id'],'material_binding':brief,
            'resources':resources,'student_access':state,'internal_only':True,
            'agent_access':{'can_read':True,'student_mask_limits_agent':False,'scope':'selected_version'},
            'unavailable_references':scope['unavailable_references'] if grading else [],
            'instruction':('本轮只核对已布置练习的冻结解答；不是批改学生。实际验算最终输出并保留字段授权，材料不足按契约保存。' if reviewing else '')+'这是当时选定并与本次作答绑定的版本；不改用题库后来更新的图/解析。只批改本次布置范围，先独立核验，参考用于交叉检查；内部阅读不代表学生已看题或看解析。'}
    conn.execute('CREATE TABLE IF NOT EXISTS tool_audit(id INTEGER PRIMARY KEY,action TEXT,record_id TEXT,created_at TEXT)')
    from app.learning.loop import stamp
    conn.execute('INSERT INTO tool_audit(action,record_id,created_at) VALUES(?,?,?)',('read_bank',binding['probe_id'],stamp()))
    return [{'type':'text','text':json.dumps(result,ensure_ascii=False)},*images]
