"""Bounded prepared candidates; the model chooses, never searches the bank."""
import copy,json
from app.bank import annotations
from app.bank.access import policy_group
from app.bank.exam_identity import metadata
from app.knowledge import catalog

VERSION='1.10'

def capture(conn,data,inputs):
    from app.bank.retrieval import recall
    from app.bank.paper_candidates import location
    from app.bank.exam_identity import candidates
    from app.learning.practice_knowledge import material_binding
    scope=inputs['practice_knowledge'];nodes={n['id']:n for n in scope['catalog_nodes']}
    report=json.loads(inputs['reports'][-1]['report_json']);diagnoses={str(q['number']):q for q in report['questions']}
    state=inputs['practice_plan']['state'];affected=set(state.get('affected_numbers',[]))
    excluded=set();loc=location(dict(conn.execute('SELECT * FROM papers WHERE id=?',(inputs['paper']['id'],)).fetchone()))
    for q in inputs['questions']:
        if q.get('match_bank_id'):excluded.update(policy_group(conn,q['match_bank_id']))
        if loc['status']=='located' and str(q['number']).isascii() and str(q['number']).isdecimal():
            for bid in candidates(conn,loc['year'],loc['math_type'],int(q['number'])):excluded.update(policy_group(conn,bid))
    goals=[];pool={};definitions={}
    retained_goals=[];retained=[]
    for row in inputs['practice_plan']['goals']:
        goal=json.loads(row['payload_json'])
        if not affected or not set(map(str,goal['question_numbers'])).intersection(affected):
            goal['id']='keep-'+row['id'];retained_goals.append(goal)
    for pid in state['probe_ids'] if state['is_current'] else []:
        if pid in scope['legacy_review']:continue
        ids=[g['id'] for g in retained_goals if conn.execute('SELECT 1 FROM probe_goals WHERE probe_id=? AND goal_id=?',(pid,g['id'][5:])).fetchone()]
        if ids:retained.append({'probe_id':pid,'goal_ids':ids})
    for goal in retained_goals:
        if not any(goal['id'] in item['goal_ids'] for item in retained):goal['decision']='monitor'
    for mapped in scope['question_mappings']:
        number=str(mapped['number']);question=diagnoses[number]
        if affected and number not in affected:continue
        if question['correctness']=='correct':continue
        for tid in mapped['mapping']['topic_ids']:
            tid=catalog.resolve(conn,tid)
            if tid not in nodes or nodes[tid].get('origin',{}).get('node_kind')!='atom':continue
            gid='target-'+number+'-'+tid
            goal={'id':gid,'label':nodes[tid]['name'],'question_numbers':[int(number)],'topic_ids':[tid],
                'stage':(question.get('first_error') or {}).get('stage','unknown'),
                'evidence':question.get('observation') or question.get('cause_summary') or '原卷已保存的薄弱证据',
                'priority':1,'decision':'practice','reason':'针对原卷薄弱原子补强','related_probe_ids':[]}
            original_type=None
            own=next((q.get('match_bank_id') for q in inputs['questions'] if str(q['number'])==number),None)
            if own:original_type=metadata(conn,own)['question_type']
            if not original_type and loc['status']=='located':
                own_ids=candidates(conn,loc['year'],loc['math_type'],int(number))
                if own_ids:original_type=metadata(conn,own_ids[0])['question_type']
            recalled=recall(conn,data,topic_ids=[tid],limit=100,internal=True,allowed_annotations=scope['annotation_manifest'])
            items=[]
            # recall is paged; collect all matches before deterministic ranking.
            offset=0
            while True:
                if offset:recalled=recall(conn,data,topic_ids=[tid],offset=offset,limit=100,internal=True,allowed_annotations=scope['annotation_manifest'])
                for item in recalled['items']:
                    if item['history']['seen_question'] or item['history']['seen_solution'] or item['history']['exercises']:continue
                    if policy_group(conn,item['id']).intersection(excluded):continue
                    typ=metadata(conn,item['id'])['question_type']
                    primary=any(catalog.resolve(conn,b['topic_id'])==tid and b['role']=='primary' for b in item['bindings'])
                    items.append((not primary,typ!=original_type,-int(item.get('year') or 0),item['id'],item))
                if recalled['next_offset'] is None:break
                offset=recalled['next_offset']
            chosen=[]
            for *_,item in sorted(items,key=lambda v:v[:4]):
                bid=item['id'];annotation=annotations.current(conn,data,bid)
                try:materials=annotations.materials(conn,data,bid)
                except ValueError as exc:
                    if str(exc)=='题库缺少可阅读题干':continue
                    raise
                question=materials.get('question') or {}
                if not question.get('text') and not question.get('path'):continue
                brief={'bank_id':bid,'annotation_id':item['annotation_id'],'question_text':question.get('text',''),
                    'methods':item['methods'],'checkpoints':item['checkpoints'],'fingerprint':item['fingerprint']}
                pool.setdefault(bid,dict(brief,binding=material_binding(conn,data,bid,annotation),
                    reference_answer=(materials.get('answer') or {}).get('text') or annotation['analysis'].get('reference_reasoning') or '按固定参考独立核验本次回答范围',
                    reference_analysis=(materials.get('analysis') or {}).get('text') or annotation['analysis'].get('reference_reasoning') or '对照固定材料核验'))
                chosen.append(bid)
                if len(chosen)==5:break
            if not chosen:goal['decision']='no_candidate'
            definitions[tid]=nodes[tid]
            goals.append({'goal':goal,'cause':{'first_error':question.get('first_error'),'cause_summary':question.get('cause_summary')},'candidate_ids':chosen})
    for g in retained_goals:
        for tid in g['topic_ids']:
            if tid in nodes:definitions[tid]=nodes[tid]
    return {'schema':'mathlens.selection-input/v1','targets':goals,'candidates':pool,'definitions':list(definitions.values()),
            'retained_goals':retained_goals,'retained_exercises':retained}

def summary(candidate):
    return {k:v for k,v in candidate.items() if k not in ('binding','reference_answer','reference_analysis')}

def public(scope):
    return dict(targets=scope['targets'],definitions=scope['definitions'],candidates=[summary(c) for c in scope['candidates'].values()])

def normalize(conn,data,task,result):
    from app.learning.tasks import require_read,digest
    from app.learning.practice_knowledge import require_binding
    inputs=json.loads(task['input_json']);scope=inputs['selection'];targets={t['goal']['id']:t for t in scope['targets']}
    if set(result['limitations'])!={*targets}:raise ValueError('每个候选目标须返回限制说明（无缺口可为空字符串）')
    counts={gid:0 for gid in targets};atoms={};used=set();exercises=[]
    for old in scope['retained_exercises']:
        row=conn.execute('SELECT bank_id FROM diagnostic_probes WHERE id=?',(old['probe_id'],)).fetchone()
        if row:
            for goal in scope['retained_goals']:
                if goal['id'] in old['goal_ids']:
                    for tid in goal['topic_ids']:atoms.setdefault(tid,set()).add(row[0])
    for i,item in enumerate(result['selections']):
        bid=item['bank_id']
        if bid in used:raise ValueError('同题须合并为一个选择并关联多个目标')
        used.add(bid)
        if not item['goal_ids'] or len(set(item['goal_ids']))!=len(item['goal_ids']):raise ValueError('选择目标不能为空或重复')
        if any(g not in targets or bid not in targets[g]['candidate_ids'] for g in item['goal_ids']):raise ValueError('只能从后端提供的对应目标候选选择')
        candidate=scope['candidates'][bid]
        require_read(conn,task,'candidate_summary',bid,'summary',digest(summary(candidate)))
        require_binding(conn,data,task,bid,candidate['annotation_id'])
        for gid in item['goal_ids']:
            counts[gid]+=1
            for tid in targets[gid]['goal']['topic_ids']:atoms.setdefault(tid,set()).add(bid)
        exercises.append(dict(item,id='selection-'+str(i+1),annotation_id=candidate['annotation_id'],
            expected=candidate['reference_answer'],solution_note=candidate['reference_analysis'],repeat_reason=None))
    if any(c>2 for c in counts.values()) or any(len(v)>3 for v in atoms.values()):raise ValueError('每目标至多2题，每原子合计至多3题（含保留练习）')
    goals=copy.deepcopy(scope['retained_goals'])
    for gid,t in targets.items():
        goal=copy.deepcopy(t['goal']);goal['decision']='practice' if counts[gid] else 'no_candidate'
        if not counts[gid] and not result['limitations'][gid].strip():raise ValueError('未选题目标须写明无合适候选的限制')
        goal['reason']=result['limitations'][gid] or goal['reason'];goals.append(goal)
    from app.learning.practice_knowledge import require_current_definitions
    require_current_definitions(conn,inputs['practice_knowledge']['catalog_nodes'],{t for g in goals for t in g['topic_ids']})
    return {'goals':goals,'exercises':exercises,'retained_exercises':scope['retained_exercises'],
            'limitations':[v for v in result['limitations'].values() if v]}
