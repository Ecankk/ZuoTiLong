"""Profile assignments own personal records and immutable materials, never a paper."""
import json,uuid
from app.learning.tasks import encode,digest
from app.learning.loop import stamp
from app.errors import ServiceError


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS profile_practice_batches(
        id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,body_json TEXT NOT NULL,
        targets_json TEXT NOT NULL,evidence_json TEXT NOT NULL,job_id TEXT,result_id TEXT,
        limitations_json TEXT NOT NULL DEFAULT '[]',created_at TEXT NOT NULL,completed_at TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS profile_practice_exercises(
        id TEXT PRIMARY KEY,batch_id TEXT NOT NULL REFERENCES profile_practice_batches(id),
        bank_id TEXT NOT NULL,goal_ids_json TEXT NOT NULL,topic_ids_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,binding_json TEXT NOT NULL,created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS profile_practice_attempts(
        id TEXT PRIMARY KEY,exercise_id TEXT NOT NULL REFERENCES profile_practice_exercises(id),
        request_id TEXT NOT NULL UNIQUE,body_json TEXT NOT NULL,assessment_json TEXT,
        answer_exposed INTEGER NOT NULL,created_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_profile_exercise_batch ON profile_practice_exercises(batch_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_profile_attempt_exercise ON profile_practice_attempts(exercise_id,created_at)')


def row(conn,table,id):
    value=conn.execute('SELECT * FROM '+table+' WHERE id=?',(id,)).fetchone()
    if value is None:raise ServiceError('画像练习记录不存在',404)
    return dict(value)


def quotas(size):
    weights=(5,3,2);base=[size*w//10 for w in weights]
    for i in sorted(range(3),key=lambda i:(-(size*weights[i]%10),i))[:size-sum(base)]:base[i]+=1
    return dict(zip(('weak','review_due','uncovered'),base))


def choose(targets,size):
    chosen=[];quota=quotas(size)
    for category,n in quota.items():chosen.extend([t for t in targets if t['category']==category][:n])
    for category in quota:
        for target in targets:
            if len(chosen)>=size:break
            if target['category']==category and target not in chosen:chosen.append(target)
    return [dict(t,goal_id='profile-target-'+t['topic_id']) for t in chosen]


def evidence(conn,topic_ids):
    """Saved semantic evidence, not a global DB version or task/UI state."""
    from app.knowledge.index import snapshot
    nodes=snapshot(conn)['nodes'];ids=set(topic_ids)
    return {n['skill_id']:[{k:e.get(k) for k in ('id','kind','created_at','verified','description')} for e in n['events']]
            for n in nodes if n['skill_id'] in ids}


def guard(conn,data,kind,scope=None,attempt_id=None):
    if kind=='grade_attempt':return capture_grade(conn,data,attempt_id)
    if not isinstance(scope,dict) or set(scope)!={'profile_batch_id'}:raise ValueError('画像选题必须指定profile_batch_id')
    batch=row(conn,'profile_practice_batches',scope['profile_batch_id'])
    targets=json.loads(batch['targets_json']);proof=evidence(conn,[t['topic_id'] for t in targets])
    if digest(proof)!=digest(json.loads(batch['evidence_json'])):raise ValueError('画像目标的已保存表现已变化，请重新创建批次')
    return {'profile_batch_id':batch['id'],'body':json.loads(batch['body_json']),'targets':targets,'evidence':proof}


def excluded(conn):
    from app.bank.originals import uploaded_originals
    from app.bank.access import policy_group,preferences
    seeds=set(uploaded_originals(conn))
    for table in ('diagnostic_probes','free_practice_attempts','profile_practice_exercises','bank_views','bank_exposures'):
        seeds.update(r[0] for r in conn.execute('SELECT DISTINCT bank_id FROM '+table))
    reserved={(r['math_type'],str(r['year'])) for r in preferences(conn)['reserved']}
    seeds.update(r['bank_id'] for r in conn.execute('SELECT * FROM bank_identity') if (r['math_type'],str(r['year'])) in reserved)
    return set().union(*(policy_group(conn,bid) for bid in sorted(seeds))) if seeds else set()


def capture(conn,data,scope):
    from app.bank.capture_view import capture as view,active
    if active(conn) is None:
        with view(conn,data):return capture(conn,data,scope)
    proof=guard(conn,data,'prepare_practice',scope)
    from app.knowledge import catalog,index
    from app.storage.annotation_cache import manifest
    from app.bank import annotations
    from app.bank.retrieval import recall
    from app.learning.practice_knowledge import material_binding
    nodes=index.catalog(conn);by_id={n['id']:n for n in nodes};origins=manifest(conn,digest)
    blocked=excluded(conn);targets=[];pool={};definitions={}
    for target in proof['targets']:
        tid=target['topic_id'];ranked=[];offset=0
        while True:
            found=recall(conn,data,topic_ids=[tid],offset=offset,limit=100,internal=True,allowed_annotations=origins)
            for item in found['items']:
                if item['id'] in blocked or item['history']['seen_question'] or item['history']['seen_solution'] or item['history']['exercises']:continue
                primary=any(catalog.resolve(conn,b['topic_id'])==tid and b['role']=='primary' for b in item['bindings'])
                ranked.append((not primary,-int(item.get('year') or 0),item['id'],item))
            if found['next_offset'] is None:break
            offset=found['next_offset']
        ids=[]
        for *_,item in sorted(ranked,key=lambda v:v[:3]):
            bid=item['id'];annotation=annotations.current(conn,data,bid)
            try:materials=annotations.materials(conn,data,bid)
            except ValueError as error:
                if str(error)=='题库缺少可阅读题干':continue
                raise
            question=materials.get('question') or {}
            if not question.get('text') and not question.get('path'):continue
            pool.setdefault(bid,dict(bank_id=bid,annotation_id=item['annotation_id'],question_text=question.get('text',''),
                methods=item['methods'],checkpoints=item['checkpoints'],fingerprint=item['fingerprint'],
                binding=material_binding(conn,data,bid,annotation),
                reference_answer=(materials.get('answer') or {}).get('text') or annotation['analysis'].get('reference_reasoning') or '按固定参考独立核验本次回答范围',
                reference_analysis=(materials.get('analysis') or {}).get('text') or annotation['analysis'].get('reference_reasoning') or '对照固定材料核验'))
            ids.append(bid)
            if len(ids)==5:break
        if tid not in by_id:raise ValueError('画像目标已不在当前目录，请重新创建批次')
        definitions[tid]=by_id[tid]
        goal=dict(id=target['goal_id'],label=target['name'],topic_ids=[tid],question_numbers=[],stage='unknown',
            evidence=proof['evidence'].get(tid,[]),priority=1,decision='practice' if ids else 'no_candidate',reason=target['reason'],related_probe_ids=[])
        targets.append(dict(goal=goal,cause={'category':target['category']},candidate_ids=ids))
    return {'profile_batch':proof,'task_scope':scope,
        'practice_knowledge':{'catalog_revision':catalog.active_id(conn),'catalog_nodes':nodes,'annotation_manifest':origins},
        'selection':dict(schema='mathlens.selection-input/v1',targets=targets,candidates=pool,definitions=list(definitions.values()),retained_goals=[],retained_exercises=[])}


def validate_input(conn,inputs,current):
    if digest(inputs['profile_batch'])!=digest(current['profile_batch']):raise ValueError('画像目标或其表现依据已变化')


def normalize(conn,data,task,result):
    from app.learning.selection import normalize as shared
    inputs=json.loads(task['input_json'])
    if len(result['selections'])>inputs['profile_batch']['body']['size']:raise ValueError('画像批次选题数超过requested_size')
    blocked=excluded(conn)
    invalid=[s['bank_id'] for s in result['selections'] if s['bank_id'] in blocked]
    if invalid:raise ValueError('候选已作答、已布置、已曝光或属于上传原卷：'+', '.join(invalid))
    return shared(conn,data,task,result)


def save_selection(conn,data,task,rid,result):
    from app.storage.practice_materials import freeze
    from app.learning.practice_knowledge import require_binding
    from app.learning.practice_presentation import metadata
    from app.knowledge import catalog
    from app.bank import annotations
    inputs=json.loads(task['input_json']);batch=inputs['profile_batch']['profile_batch_id'];goals={g['id']:g for g in result['goals']}
    for item in result['exercises']:
        binding=freeze(conn,data,require_binding(conn,data,task,item['bank_id'],item['annotation_id']))
        topics=sorted({t for gid in item['goal_ids'] for t in goals[gid]['topic_ids']})
        annotation=annotations.current(conn,data,item['bank_id'])['analysis']
        binding.update(topic_ids=topics,definitions=[n for n in inputs['practice_knowledge']['catalog_nodes'] if n['id'] in topics],
            annotation=annotation,source_metadata=metadata(conn,item['bank_id']))
        from app.bank.errata import markers
        binding['errata']=markers(conn,item['bank_id'])
        eid='profile-exercise-'+uuid.uuid5(uuid.NAMESPACE_URL,batch+':'+item['bank_id']).hex
        payload=dict(item,goals=[goals[g] for g in item['goal_ids']])
        conn.execute('INSERT INTO profile_practice_exercises VALUES(?,?,?,?,?,?,?,?)',
            (eid,batch,item['bank_id'],encode(item['goal_ids']),encode(topics),encode(payload),encode(binding),stamp()))
    limitations=[{'goal_id':g['id'],'reason':g['reason']} for g in result['goals'] if g['decision']!='practice']
    actual=len(result['exercises']);requested=inputs['profile_batch']['body']['size']
    if actual<requested:limitations.append({'goal_id':None,'reason':f'这次找到{actual}道适合练的题，没凑满想要的{requested}道。做过、看过答案或留作整卷的题不会拿来凑数。'})
    conn.execute('UPDATE profile_practice_batches SET result_id=?,completed_at=?,limitations_json=? WHERE id=?',(rid,stamp(),encode(limitations),batch))
    return {'batch_id':batch,'source':'profile_practice'}


def capture_grade(conn,data,aid):
    attempt=row(conn,'profile_practice_attempts',aid);exercise=row(conn,'profile_practice_exercises',attempt['exercise_id'])
    binding=json.loads(exercise['binding_json']);body=json.loads(attempt['body_json'])
    from app.storage.practice_materials import load
    from app.storage.images import image_records,image_path
    from app.learning.tasks import resource_digest
    load(data,binding['snapshot_key'],binding['snapshot_sha256'])
    return {'profile_practice':dict(id=aid,exercise_id=exercise['id'],batch_id=exercise['batch_id'],bank_id=exercise['bank_id'],
        body=body,snapshot=binding,assignment=json.loads(exercise['payload_json']),answer_exposed=bool(attempt['answer_exposed']),
        image_sha256=[resource_digest(image_path(i,data),data) for i in image_records(conn,body['image_ids'])])}


def save_grade(conn,task,inputs,result,rid):
    from app.learning.tasks import require_read
    scope=inputs['profile_practice']
    if result['attempt_id']!=scope['id']:raise ValueError('批改引用其他画像作答')
    require_read(conn,task,'profile_practice',scope['id'],'materials',digest(scope))
    if set(result['topic_ids'])-set(scope['snapshot']['topic_ids']):raise ValueError('批改引用固定回答范围以外的考点')
    conn.execute('UPDATE profile_practice_attempts SET assessment_json=? WHERE id=?',(encode(dict(result,task_result_id=rid)),scope['id']))
    return {'attempt_id':scope['id'],'source':'profile_practice'}


def topic_events(conn):
    for r in conn.execute('SELECT a.*,e.topic_ids_json FROM profile_practice_attempts a JOIN profile_practice_exercises e ON e.id=a.exercise_id WHERE a.assessment_json IS NOT NULL'):
        a=json.loads(r['assessment_json']);correct=a.get('correct')
        for tid in set(a.get('topic_ids',[]))&set(json.loads(r['topic_ids_json'])):
            kind='unknown' if correct is None else ('assisted_success' if r['answer_exposed'] else 'probe_success') if correct else 'probe_failure'
            yield tid,dict(id=r['id']+':'+tid,source='profile_practice',attempt_id=r['id'],question_id=None,paper_id=None,
                kind=kind,created_at=r['created_at'],verified=True,description=a['feedback'])


def public_attempt(conn,r):
    from app.learning.feedback import info
    from app.learning.practice_presentation import reference
    r=dict(r);body=json.loads(r['body_json']);assessment=json.loads(r['assessment_json']) if r['assessment_json'] else None
    job=conn.execute('SELECT id,status FROM workflow_jobs WHERE attempt_id=? ORDER BY rowid DESC LIMIT 1',(r['id'],)).fetchone()
    return dict(body,**info(conn,'profile_practice',r['id'],assessment),id=r['id'],attempt_id=r['id'],probe_id=r['exercise_id'],
        source='profile_practice',assessment=reference(assessment) if assessment else None,answer_exposed=bool(r['answer_exposed']),created_at=r['created_at'],job=dict(job) if job else None)


def cards(conn,include_access=True):
    from app.bank.access import access
    from app.learning.practice_presentation import correctness
    result=[]
    for r in conn.execute('SELECT * FROM profile_practice_exercises ORDER BY created_at,id'):
        binding=json.loads(r['binding_json']);payload=json.loads(r['payload_json'])
        latest=conn.execute('SELECT * FROM profile_practice_attempts WHERE exercise_id=? ORDER BY rowid DESC LIMIT 1',(r['id'],)).fetchone()
        assessed=json.loads(latest['assessment_json']) if latest and latest['assessment_json'] else None
        state=None
        if include_access:
            try:state=access(conn,r['bank_id'])
            except ValueError:state=dict(can_view=True,reserved=False,analysis_allowed=bool(latest and latest['assessment_json']))
            state.update(binding['source_metadata'])
        result.append(dict(id=r['id'],origin='profile',latest_correctness=correctness(assessed),batch_id=r['batch_id'],batch_title='画像选题',
            paper_id=None,paper_title=None,question_id=None,bank_id=r['bank_id'],created_at=r['created_at'],
            status='pending' if not latest else 'grading' if not assessed else 'needs_supplement' if assessed.get('correct') is None else 'graded',
            goal_ids=json.loads(r['goal_ids_json']),topics=[{'topic_id':n['id'],'name':n['name']} for n in binding['definitions']],
            access=state,latest_attempt_id=latest['id'] if latest else None))
    return result


def supplement(conn,data,task,action,payload,image_content):
    from app.learning.free_practice import supplement as fixed
    scope=json.loads(task['input_json'])['profile_practice']
    return fixed(conn,data,task,action,payload,image_content,scope=scope)


class ProfilePracticeService:
    def __init__(self,rt=None,*,config=None,database=None):
        self.rt=rt;self.config=config or rt.config;self.database=database or rt.database

    def create(self,body):
        body=dict(body);body['scope']=body.get('scope') or {}
        if body.get('confirmed') is not True or type(body.get('size')) is not int or body['size'] not in (5,8,10):raise ValueError('请确认并选择5、8或10题')
        body['request_id']=str(uuid.UUID(body['request_id']))
        with self.database.session() as conn:
            old=conn.execute('SELECT * FROM profile_practice_batches WHERE request_id=?',(body['request_id'],)).fetchone()
            if old:
                if old['body_json']!=encode(body):raise ServiceError('同request_id不能更换画像选题范围',409)
                return self.created(dict(old),True)
        d=self.rt.profile.data()
        if not d['prefs']['study_type'] or not d['release']:raise ServiceError('请先设置备考类别并发布题库目录',409)
        targets=self.rt.profile.targets(d,body['scope'].get('subject'),body['scope'].get('chapter_topic_id'))
        # Within categories: latest failures first, assisted-only/oldest due first;
        # stable topic ID resolves ties without randomizing targets.
        def priority(t):
            n=d['nodes'][t['topic_id']];last=n['last_attempt_at'] or ''
            if t['category']=='weak':return (0,-n['failures'],tuple(-ord(c) for c in last),t['topic_id'])
            if t['category']=='review_due':return (1,not (n['assisted'] and not n['successes']),last,t['topic_id'])
            return (2,t['topic_id'])
        targets.sort(key=priority)
        targets=choose(targets,body['size'])
        if not targets:raise ServiceError('当前范围没有可选画像目标',409)
        from app.learning.tasks import atomic,task_write
        with self.database.session() as conn:
            with atomic(conn):
                versions=tuple(conn.execute('PRAGMA '+db+'.data_version').fetchone()[0] for db in ('main','library'))
                proof=evidence(conn,[t['topic_id'] for t in targets])
                saved={n['skill_id']:[{k:e.get(k) for k in ('id','kind','created_at','verified','description')} for e in n['events']]
                       for n in d['snapshot']['nodes'] if n['skill_id'] in {t['topic_id'] for t in targets}}
                if digest(saved)!=digest(proof):raise ServiceError('画像依据已变化，请重试',409)
            with task_write(conn,versions):
                return self._insert(conn,body,targets,proof)

    def _insert(self,conn,body,targets,proof):
            old=conn.execute('SELECT * FROM profile_practice_batches WHERE request_id=?',(body['request_id'],)).fetchone()
            if old:
                if old['body_json']!=encode(body):raise ServiceError('同request_id不能更换画像选题范围',409)
                return self.created(dict(old),True)
            if conn.execute("SELECT 1 FROM profile_practice_batches b JOIN workflow_jobs j ON j.id=b.job_id WHERE json_extract(b.body_json,'$.scope')=? AND j.status IN ('queued','dispatching','running')",(encode(body['scope']),)).fetchone():raise ServiceError('该范围已有画像选题正在生成',409)
            bid='profile-batch-'+uuid.uuid5(uuid.NAMESPACE_URL,body['request_id']).hex
            conn.execute('INSERT INTO profile_practice_batches(id,request_id,body_json,targets_json,evidence_json,created_at) VALUES(?,?,?,?,?,?)',
                (bid,body['request_id'],encode(body),encode(targets),encode(proof),stamp()))
            from app.learning.workflows import enqueue
            # Prepared semantic guard is already checked above, outside the
            # write transaction. Candidate capture is performed by the worker.
            job=enqueue(conn,self.config.root,self.config.data,'prepare_practice',None,body['request_id'],task_scope={'profile_batch_id':bid},contract_version='1.12',
                prepared_guard={'profile_batch_id':bid,'body':body,'targets':targets,'evidence':proof})
            conn.execute('UPDATE profile_practice_batches SET job_id=? WHERE id=?',(job['id'],bid))
            return self.created(row(conn,'profile_practice_batches',bid),False)

    def created(self,batch,reused):
        return dict(batch_id=batch['id'],source='profile_practice',requested_size=json.loads(batch['body_json'])['size'],status='queued',job_id=batch['job_id'],reused=reused)

    def batch(self,bid):
        with self.database.session() as conn:
            batch=row(conn,'profile_practice_batches',bid);body=json.loads(batch['body_json']);cs=[c for c in cards(conn,False) if c['batch_id']==bid]
            job=row(conn,'workflow_jobs',batch['job_id'])
            status=('ready' if cs else 'no_candidates') if batch['result_id'] else {'completed':'no_candidates','abandoned':'cancelled','failed':'failed','interrupted':'failed','blocked':'failed','dispatching':'selecting','running':'selecting'}.get(job['status'],'queued')
            return dict(id=bid,source='profile_practice',title='画像选题',requested_size=body['size'],status=status,created_at=batch['created_at'],completed_at=batch['completed_at'],scope=body['scope'],
                job_id=job['id'],result_id=batch['result_id'],actual_size=len(cs),practice_ids=[c['id'] for c in cs],targets=json.loads(batch['targets_json']),limitations=json.loads(batch['limitations_json']),
                counts={s:sum(c['status']==s for c in cs) for s in ('pending','grading','graded','needs_supplement')},error=job['error'])

    def detail(self,eid):
        from app.learning.practice_presentation import reference
        with self.database.session() as conn:
            exercise=row(conn,'profile_practice_exercises',eid);binding=json.loads(exercise['binding_json']);payload=json.loads(exercise['payload_json'])
            card=next(c for c in cards(conn) if c['id']==eid);state=card['access'];question={}
            latest=conn.execute('SELECT * FROM profile_practice_attempts WHERE id=?',(card['latest_attempt_id'],)).fetchone()
            for role,item in binding['material_manifest']['resources'].items():
                if role!='question' and not (latest and state['analysis_allowed']):continue
                question[role+'_text']=item['text']
                if item['image_file']:question[role+'_image']=f'/api/practices/{eid}/materials/{role}'
            if latest and state['analysis_allowed']:question.update(expected=payload['expected'],solution_note=payload['solution_note'])
            actions=[] if state['reserved'] else ['reveal_question'] if not state['can_view'] else ['supplement' if latest else 'submit']+(['reveal_analysis'] if latest and not state['analysis_allowed'] else [])
            return dict(practice=card,is_current=True,review_reason=None,question=reference(question) if state['can_view'] else None,
                goals=payload['goals'],selection_reason=payload['selection_reason'] if state['can_view'] else None,latest_attempt=public_attempt(conn,latest) if latest else None,actions=actions)

    def history(self,eid,offset=0,limit=20):
        from app.services.frontend_reads import page
        with self.database.session() as conn:
            row(conn,'profile_practice_exercises',eid)
            records=list(conn.execute('SELECT * FROM profile_practice_attempts WHERE exercise_id=? ORDER BY rowid DESC',(eid,)))
            p=page(records,offset,limit);p['items']=[public_attempt(conn,r) for r in p['items']];return p

    def submit(self,eid,body,*,supplement_id=None):
        from app.storage.images import image_records
        from app.bank.access import policy_group
        body=dict(dict(response='',image_ids=[],image_roles={},answer_exposed=False,elapsed_seconds=None),**body)
        request_id=str(uuid.UUID(body.get('request_id') or ''))
        with self.database.session(write=True) as conn:
            exercise=row(conn,'profile_practice_exercises',eid)
            old=conn.execute('SELECT * FROM profile_practice_attempts WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['exercise_id']!=eid or old['body_json']!=encode(body):raise ServiceError('同request_id不能用于不同作答',409)
                return dict(attempt_id=old['id'],reused=True,job=public_attempt(conn,old)['job'])
            latest=conn.execute('SELECT * FROM profile_practice_attempts WHERE exercise_id=? ORDER BY rowid DESC LIMIT 1',(eid,)).fetchone()
            if latest and not supplement_id:raise ServiceError('已提交过，请补充作答',409)
            if supplement_id and (not latest or latest['id']!=supplement_id):raise ServiceError('只能补充最新作答',409)
            if supplement_id and conn.execute("SELECT 1 FROM workflow_jobs WHERE attempt_id=? AND status IN ('dispatching','running')",(supplement_id,)).fetchone():raise ServiceError('批改运行中，暂不能补充',409)
            image_records(conn,body['image_ids'])
            if set(body['image_roles'])-set(body['image_ids']) or any(v not in ('own_work','marking','external_solution') for v in body['image_roles'].values()):raise ValueError('图片角色无效')
            if not body['response'].strip() and not body['image_ids']:raise ValueError('请提交作答')
            try:
                from app.bank.access import access
                state=access(conn,exercise['bank_id'])
            except ValueError:state=dict(can_view=True,reserved=False)
            if state['reserved'] or not state['can_view']:
                from app.learning.practice_presentation import denied
                denied(state)
            group=policy_group(conn,exercise['bank_id'])
            exposed=bool(body['answer_exposed'] or any(v!='own_work' for v in body['image_roles'].values()) or any(conn.execute('SELECT 1 FROM bank_exposures WHERE bank_id=?',(bid,)).fetchone() for bid in group) or latest and (latest['answer_exposed'] or latest['assessment_json']))
            aid=latest['id'] if supplement_id else 'profile-attempt-'+uuid.uuid4().hex
            if latest:
                conn.execute("UPDATE workflow_jobs SET status='superseded',updated_at=? WHERE attempt_id=? AND status='queued'",(stamp(),latest['id']))
            if supplement_id:
                conn.execute('INSERT INTO record_versions VALUES(?,?,?,?,?,?)',('version-'+uuid.uuid4().hex,'attempt',aid,encode(dict(latest)),'画像作答补充前版本',stamp()))
                conn.execute('UPDATE profile_practice_attempts SET request_id=?,body_json=?,assessment_json=NULL,answer_exposed=? WHERE id=?',(request_id,encode(body),int(exposed),aid))
            else:conn.execute('INSERT INTO profile_practice_attempts VALUES(?,?,?,?,?,?,?)',(aid,eid,request_id,encode(body),None,int(exposed),stamp()))
            from app.learning.workflows import enqueue
            job=enqueue(conn,self.config.root,self.config.data,'grade_attempt',None,str(uuid.uuid5(uuid.NAMESPACE_URL,'profile-grade:'+aid+':'+digest(body))),aid,contract_version='1.12')
            return dict(attempt_id=aid,reused=False,job={'id':job['id'],'status':job['status']})

    def supplement(self,aid,body):
        with self.database.session() as conn:exercise=row(conn,'profile_practice_attempts',aid)['exercise_id']
        return self.submit(exercise,body,supplement_id=aid)

    def image(self,eid,role):
        with self.database.session() as conn:
            exercise=row(conn,'profile_practice_exercises',eid)
            detail=self.detail(eid)
            if role!='question' and not (detail['latest_attempt'] and detail['practice']['access']['analysis_allowed']):raise ServiceError('请先提交并解锁解析',403)
            if not detail['practice']['access']['can_view']:raise ServiceError('题面尚未解锁',403)
            from app.storage.practice_materials import image_path
            return image_path(self.config.data,json.loads(exercise['binding_json']),role)
