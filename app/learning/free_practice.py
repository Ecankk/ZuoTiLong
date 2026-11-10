"""Private, repeatable bank attempts with immutable materials and no paper fiction."""
import json,re,uuid,unicodedata,math
from pathlib import Path
from app.learning.tasks import digest,encode
from app.learning.loop import stamp
from app.errors import ServiceError

def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS free_practice_attempts(
      id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,bank_id TEXT NOT NULL,
      body_json TEXT NOT NULL,snapshot_json TEXT NOT NULL,assessment_json TEXT,
      answer_exposed INTEGER NOT NULL,created_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_free_bank ON free_practice_attempts(bank_id,created_at)')

def normal(value):
    value=unicodedata.normalize('NFKC',value).strip().replace('$','')
    value=re.sub(r'\\(?:left|right)(?![A-Za-z])','',value)
    for a,b in ((r'\dfrac',r'\frac'),(r'\tfrac',r'\frac'),(r'\,',''),(r'\!','')):value=value.replace(a,b)
    return re.sub(r'\s+','',value)

def choice(value):
    value=normal(value).upper()
    value=re.sub(r'^\\(?:TEXT|MATHRM)\{([A-D])\}$',r'\1',value)
    if re.fullmatch(r'\([A-D]\)',value):value=value[1:-1]
    return value if re.fullmatch('[A-D]',value) else None

def record(conn,aid):
    row=conn.execute('SELECT * FROM free_practice_attempts WHERE id=?',(aid,)).fetchone()
    if not row:raise ServiceError('自由练习作答不存在',404)
    return dict(row)

def display_text(role,item):
    text=item['text']
    if item['image_file'] and not text.strip():return None
    # Legacy image navigation labels are not a transcription of the question.
    if item['image_file'] and (role=='question' and re.match(r'^\d{4}\s+数学[一二三]\s+第\s*\d+\s*题\s*[·•]',text)
                               or role=='analysis' and text.strip() in ('参考解析见原图','参考解析见原图。')):return None
    return text

def capture(conn,data,aid):
    row=record(conn,aid);snapshot=json.loads(row['snapshot_json']);body=json.loads(row['body_json'])
    from app.storage.practice_materials import load
    load(data,snapshot['snapshot_key'],snapshot['snapshot_sha256'])
    from app.storage.images import image_records,image_path
    from app.learning.tasks import resource_digest
    return {'free_practice':{'id':aid,'bank_id':row['bank_id'],'body':body,'snapshot':snapshot,
        'answer_exposed':bool(row['answer_exposed']),
        'image_sha256':[resource_digest(image_path(i,data),data) for i in image_records(conn,body['image_ids'])]}}

def public(conn,row):
    row=dict(row);body=json.loads(row['body_json'])
    snapshot=json.loads(row['snapshot_json']);question={};reference={}
    for role,item in snapshot['material_manifest']['resources'].items():
        target=question if role=='question' else reference
        if item['text'] or item['image_file']:target[role+'_text']=display_text(role,item)
        if item['image_file']:target[role+'_image']=f'/api/bank/{row["bank_id"]}/practice/attempts/{row["id"]}/materials/{role}'
    reference['errata']=snapshot.get('errata',[])
    from app.learning.practice_presentation import reference as clean_reference
    assessment=json.loads(row['assessment_json']) if row['assessment_json'] else None
    reference=clean_reference(reference,assessment)
    if assessment:assessment=clean_reference(assessment,reference)
    job=conn.execute('SELECT id,status FROM workflow_jobs WHERE attempt_id=? ORDER BY rowid DESC LIMIT 1',(row['id'],)).fetchone()
    from app.learning.feedback import info
    return {**body,**info(conn,'free_practice',row['id'],row['assessment_json']),'id':row['id'],'bank_id':row['bank_id'],'source':'free_practice',
        'question_type':snapshot['question_type'],'collection_id':snapshot['collection_id'],
        'materials':{'question':question,'reference':reference if row['assessment_json'] else None},
        'answer_exposed':bool(row['answer_exposed']),'created_at':row['created_at'],
        'assessment':assessment,'job':dict(job) if job else None}

def counts(conn,topic_id=None):
    result=dict(total=0,correct=0,wrong=0,pending=0,independent_correct=0,assisted_correct=0)
    from app.storage.boundaries import table_exists
    if not table_exists(conn,'free_practice_attempts'):return result
    from app.bank.access import preferences
    if not preferences(conn).get('include_free_practice',True):return result
    for row in conn.execute('SELECT * FROM free_practice_attempts'):
        snap=json.loads(row['snapshot_json']);assessment=json.loads(row['assessment_json'] or 'null')
        if topic_id and topic_id not in snap['topic_ids']:continue
        result['total']+=1
        correct=assessment.get('correct') if assessment else None
        result['pending' if correct is None else 'correct' if correct else 'wrong']+=1
        if correct is True:result['assisted_correct' if row['answer_exposed'] else 'independent_correct']+=1
    return result

def topic_events(conn):
    """Only explicitly observed atoms affect mastery; whole-answer grades do not."""
    from app.bank.access import preferences
    from app.storage.boundaries import table_exists
    if not table_exists(conn,'free_practice_attempts'):return
    if not preferences(conn).get('include_free_practice',True):return
    for row in conn.execute('SELECT * FROM free_practice_attempts WHERE assessment_json IS NOT NULL'):
        assessment=json.loads(row['assessment_json']);known=json.loads(row['snapshot_json'])['topic_ids']
        correct=assessment.get('correct')
        for tid in set(assessment.get('topic_ids',[]))&set(known):
            kind='unknown' if correct is None else ('assisted_success' if row['answer_exposed'] else 'probe_success') if correct else 'probe_failure'
            yield tid,dict(id=row['id']+':'+tid,source='free_practice',attempt_id=row['id'],question_id=None,paper_id=None,
                kind=kind,created_at=row['created_at'],verified=True,description=assessment['feedback'])

class FreePracticeService:
    def __init__(self,config,database):self.config,self.database=config,database

    def history(self,bid,offset=0,limit=20):
        with self.database.session() as conn:
            values=list(conn.execute('SELECT * FROM free_practice_attempts WHERE bank_id=? ORDER BY created_at DESC,rowid DESC',(bid,)))
            if not values and not conn.execute('SELECT 1 FROM bank_questions WHERE id=?',(bid,)).fetchone():raise ServiceError('题库题目不存在',404)
            return dict(items=[public(conn,r) for r in values[offset:offset+limit]],total=len(values),offset=offset,limit=limit)

    def _snapshot(self,conn,bid,*,freeze_materials=True):
        from app.bank.access import require_access
        from app.bank.access import access
        if not conn.execute('SELECT 1 FROM bank_questions WHERE id=?',(bid,)).fetchone():raise ServiceError('题库题目不存在',404)
        state=access(conn,bid)
        if state['reserved'] or not state['can_view']:
            from app.learning.practice_presentation import denied
            denied(state)
        from app.bank.annotations import materials,current
        actual=materials(conn,self.config.data,bid)
        from app.storage.practice_materials import freeze
        binding=dict(bank_id=bid,material_revision=digest(actual),content_revision=actual['question']['sha256'])
        if freeze_materials:binding=freeze(conn,self.config.data,binding)
        else:binding['material_manifest']={'resources':{r:{'text':v['text'],'image_file':Path(v['path']).name if v['path'] else None} for r,v in actual.items()}}
        from app.bank.exam_identity import metadata
        typ=metadata(conn,bid)['question_type']
        annotation=current(conn,self.config.data,bid)
        analysis=annotation.get('analysis') if annotation else None
        if analysis is None and annotation and annotation.get('payload_json'):analysis=json.loads(annotation['payload_json'])
        topics=sorted({b['topic_id'] for b in (analysis or {}).get('bindings',[])})
        from app.knowledge.index import catalog
        binding.update(question_type=typ,collection_id=conn.execute('SELECT collection_id FROM bank_questions WHERE id=?',(bid,)).fetchone()[0],
            annotation=analysis,topic_ids=topics,definitions=[n for n in catalog(conn) if n['id'] in topics])
        from app.bank.errata import markers
        binding['errata']=markers(conn,bid)
        binding['source']={**{k:state[k] for k in ('math_type','year','number')},**metadata(conn,bid)}
        return binding,state

    def view(self,bid):
        with self.database.session() as conn:
            latest=conn.execute('SELECT * FROM free_practice_attempts WHERE bank_id=? ORDER BY rowid DESC LIMIT 1',(bid,)).fetchone()
            if latest:snapshot=json.loads(latest['snapshot_json'])
            else:snapshot,state=self._snapshot(conn,bid,freeze_materials=False)
            from app.bank.access import access
            try:state=access(conn,bid)
            except ValueError:state={'can_view':False,'reserved':False,'analysis_allowed':False}
            if not latest and (state['reserved'] or not state['can_view']):
                from app.learning.practice_presentation import denied
                denied(state)
            reference=bool(latest and latest['assessment_json']) or state['analysis_allowed']
            resources=snapshot['material_manifest']['resources'];question={};refs={}
            for role,item in resources.items():
                target=question if role=='question' else refs
                if item['text'] or item['image_file']:target[role+'_text']=display_text(role,item)
                if item['image_file'] and latest:target[role+'_image']=f'/api/bank/{bid}/practice/attempts/{latest["id"]}/materials/{role}'
                elif item['image_file']:target[role+'_image']=f'/api/bank/{bid}/{role}'
            refs['errata']=snapshot.get('errata',[])
            from app.learning.practice_presentation import reference as clean_reference
            refs=clean_reference(refs,json.loads(latest['assessment_json']) if latest and latest['assessment_json'] else None)
            total=conn.execute('SELECT count(*) FROM free_practice_attempts WHERE bank_id=?',(bid,)).fetchone()[0]
            return dict(bank_id=bid,question_type=snapshot['question_type'],collection_id=snapshot['collection_id'],question=question,
                source=snapshot['source'],
                reference=refs if reference else None,actions=(['submit','reveal_analysis'] if state['can_view'] and not state['reserved'] else []),
                latest_attempt=public(conn,latest) if latest else None,attempt_count=total)

    def submit(self,bid,body):
        try:request_id=str(uuid.UUID(body['request_id']))
        except (KeyError,ValueError,TypeError,AttributeError):raise ValueError('request_id必须是UUID') from None
        body={**dict(response='',image_ids=[],image_roles={},answer_exposed=False,elapsed_seconds=None,choice=None),**body,'request_id':request_id}
        if not isinstance(body['response'],str) or not isinstance(body['answer_exposed'],bool):raise ValueError('作答格式无效')
        if len(body['response'])>16000:raise ValueError('作答最多16000字')
        elapsed=body['elapsed_seconds']
        if elapsed is not None and (isinstance(elapsed,bool) or not isinstance(elapsed,(int,float)) or not math.isfinite(elapsed) or elapsed<0):raise ValueError('作答耗时无效')
        from app.storage.images import image_records
        with self.database.session(write=True) as conn:
            old=conn.execute('SELECT * FROM free_practice_attempts WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['bank_id']!=bid or old['body_json']!=encode(body):raise ServiceError('request_id已用于不同作答',409)
                return public(conn,old)
            image_records(conn,body['image_ids'])
            if set(body['image_roles'])-set(body['image_ids']) or any(r not in ('own_work','marking','external_solution') for r in body['image_roles'].values()):raise ValueError('图片角色无效')
            if not body['response'].strip() and not body['choice'] and not body['image_ids']:raise ValueError('请提交作答')
            from app.bank.access import access,policy_group,reveal
            if not conn.execute('SELECT 1 FROM bank_questions WHERE id=?',(bid,)).fetchone():raise ServiceError('题库题目不存在',404)
            state=access(conn,bid)
            if state['reserved'] or not state['can_view']:
                from app.learning.practice_presentation import denied
                denied(state)
            snapshot,state=self._snapshot(conn,bid)
            group=policy_group(conn,bid)
            exposed=body['answer_exposed'] or any(conn.execute('SELECT 1 FROM bank_exposures WHERE bank_id=?',(i,)).fetchone() for i in group) or any(r!='own_work' for r in body['image_roles'].values())
            answer=snapshot['material_manifest']['resources'].get('answer',{}).get('text','')
            typ=snapshot['question_type'];correct=None
            if typ=='选择题' and choice(answer):
                selected=choice(body['choice'] or body['response'])
                if selected is None:raise ValueError('请选择A、B、C或D')
                correct=selected==choice(answer)
            elif typ=='填空题' and normal(answer) and normal(body['response'])==normal(answer):correct=True
            aid='free-'+uuid.uuid4().hex
            assessment=None
            if correct is not None:assessment=dict(attempt_id=aid,correct=correct,answer_status='correct' if correct else 'wrong',feedback='回答正确' if correct else '所选答案不正确',reference_reasoning=answer,observations=[],first_error=None,possible_causes=[],topic_ids=[],next_step='',needs_material=[])
            conn.execute('INSERT INTO free_practice_attempts VALUES(?,?,?,?,?,?,?,?)',(aid,request_id,bid,encode(body),encode(snapshot),encode(assessment) if assessment else None,int(bool(exposed)),stamp()))
            if assessment:reveal(conn,bid,'analysis',True)
            else:
                from app.learning.workflows import enqueue
                enqueue(conn,self.config.root,self.config.data,'grade_attempt',None,str(uuid.uuid5(uuid.NAMESPACE_URL,'free-grade:'+aid)),aid,contract_version='1.11')
            return public(conn,record(conn,aid))

    def image(self,bid,aid,role):
        with self.database.session() as conn:
            row=record(conn,aid)
            if row['bank_id']!=bid or role not in ('question','answer','analysis'):raise ServiceError('材料不存在',404)
            if role!='question' and not row['assessment_json']:
                from app.bank.access import require_access
                require_access(conn,bid,role)
            from app.storage.practice_materials import image_path
            return image_path(self.config.data,json.loads(row['snapshot_json']),role)

def save(conn,task,inputs,result,rid):
    from app.learning.tasks import require_read
    scope=inputs['free_practice'];aid=scope['id']
    if result['attempt_id']!=aid:raise ValueError('批改结果引用其他作答')
    require_read(conn,task,'free_practice',aid,'materials',digest(scope))
    # Whole-question correctness does not assert every bound atom is mastered.
    known=set(scope['snapshot']['topic_ids'])
    if set(result['topic_ids'])-known:raise ValueError('批改引用快照外考点')
    conn.execute('UPDATE free_practice_attempts SET assessment_json=? WHERE id=?',(encode({**result,'task_result_id':rid}),aid))
    from app.bank.access import record_view
    if conn.execute('SELECT 1 FROM bank_identity WHERE bank_id=?',(scope['bank_id'],)).fetchone():record_view(conn,scope['bank_id'],'analysis')
    return {'attempt_id':aid,'source':'free_practice'}

def supplement(conn,data,task,action,payload,image_content):
    """Supplemental tools must stay on the captured version, even after a library swap."""
    scope=json.loads(task['input_json'])['free_practice'];images=[]
    if action=='read_bank':
        if payload.get('bank_id')!=scope['bank_id']:raise ValueError('仅可读取本次自由练习固定题目')
        from app.storage.practice_materials import load,image_path
        binding=scope['snapshot'];manifest=load(data,binding['snapshot_key'],binding['snapshot_sha256'])
        role=payload.get('role','question');roles=list(manifest['resources']) if role=='all' else [role]
        if any(r not in manifest['resources'] for r in roles):raise ValueError('固定快照没有此角色材料')
        result={'bank_id':scope['bank_id'],'resources':{r:manifest['resources'][r] for r in roles}}
        for role in roles:
            if manifest['resources'][role]['image_file']:images.append(image_content(image_path(data,binding,role),data))
    elif action=='read_attempt':
        if payload.get('attempt_id')!=scope['id']:raise ValueError('仅可读取本次自由练习作答')
        result={'attempt_id':scope['id'],**scope['body'],'answer_exposed':scope['answer_exposed']}
        from app.storage.images import image_records,image_path
        for row in image_records(conn,scope['body']['image_ids']):images.append(image_content(image_path(row,data),data))
    else:
        definitions=scope['snapshot']['definitions'];requested=payload.get('topic_ids',[])
        if set(requested)-{n['id'] for n in definitions}:raise ValueError('仅可读取本次固定考点定义')
        result={'definitions':[n for n in definitions if not requested or n['id'] in requested]}
    return [{'type':'text','text':json.dumps(result,ensure_ascii=False)},*images]

