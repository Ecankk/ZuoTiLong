"""Deterministic prepared-question recall, without pedagogical ranking."""
import hashlib
import json
from app.bank import annotations
from app.bank.access import access, policy_group
from app.learning.plans import practice_state
from app.knowledge import catalog


def _history(conn, related, plan_cache):
    probes=[];attempts=0;active_pending=False
    for bid in sorted(related):
        for row in conn.execute('''SELECT p.*,pp.archived_at FROM diagnostic_probes p
            JOIN papers pp ON pp.id=p.paper_id WHERE p.bank_id=? ORDER BY p.id''',(bid,)):
            answers=conn.execute('SELECT assessment_json FROM probe_attempts WHERE probe_id=? ORDER BY created_at,rowid',(row['id'],)).fetchall()
            attempts+=len(answers)
            assessment=json.loads(answers[-1]['assessment_json']) if answers and answers[-1]['assessment_json'] else None
            status=('unanswered' if not answers else 'awaiting_grading' if assessment is None else
                    'needs_material' if assessment.get('correct') is None else 'reviewed')
            if row['paper_id'] not in plan_cache:plan_cache[row['paper_id']]=practice_state(conn,row['paper_id'])
            plan=plan_cache[row['paper_id']]
            retired=bool(conn.execute('SELECT 1 FROM retired_probes WHERE probe_id=?',(row['id'],)).fetchone())
            reusable=not row['archived_at'] and not retired and plan['is_current'] and row['id'] in plan['probe_ids']
            pending=not answers or status in ('awaiting_grading','needs_material')
            active_pending=active_pending or (not row['archived_at'] and not retired and pending)
            probes.append({'probe_id':row['id'],'paper_id':row['paper_id'],'question_id':row['question_id'],'bank_id':row['bank_id'],
                           'status':status,'can_reuse':bool(reusable),'retired':retired,'archived':bool(row['archived_at'])})
    views=[r[0] for bid in related for r in conn.execute('SELECT role FROM bank_views WHERE bank_id=?',(bid,))]
    exposed=any(conn.execute('SELECT 1 FROM bank_exposures WHERE bank_id=?',(bid,)).fetchone() for bid in related)
    return {'attempt_count':attempts,'seen_question':any(v in ('question','seen_question') for v in views),
            'seen_solution':bool(exposed or 'analysis' in views),'active_pending':bool(active_pending),'exercises':probes}


def recall(conn,data,*,topic_ids,stages=None,methods=None,offset=0,limit=30,include_history=False,internal=False,allowed_annotations=None):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
        raise ValueError('原子题库查询分页不合法')
    if type(include_history) is not bool:raise ValueError('include_history须为布尔值')
    if allowed_annotations is not None and not internal:raise ValueError('标注快照范围仅用于内部学习任务')
    # Keep the release, dependency validity and history in one SQLite snapshot.
    # No mutation is performed; a caller's outer transaction remains intact.
    with catalog.atomic(conn):
        return _recall(conn,data,topic_ids,stages,methods,offset,limit,include_history,internal,allowed_annotations)


def _recall(conn,data,topic_ids,stages,methods,offset,limit,include_history,internal,allowed_annotations):
    revision,matches=annotations.matching(conn,data,topic_ids=topic_ids,stages=stages,methods=methods)
    items=[];existing=[];omitted={'attempted_or_solution_seen':0,'pending_existing':0};plans={}
    for match in matches:
        if allowed_annotations is not None and match['id'] not in allowed_annotations:
            omitted['not_in_task_snapshot']=omitted.get('not_in_task_snapshot',0)+1
            continue
        related=policy_group(conn,match['bank_id'])
        history=_history(conn,related,plans)
        state=access(conn,match['bank_id'])
        metadata={'id':match['bank_id'],'entity_id':match['entity_id'],'math_type':state['math_type'],
                  'year':state['year'],'number':state['number'],'student_access':state,
                  'annotation_id':match['id'],'content_revision':match['content_revision'],
                  'annotation_catalog_revision':match['catalog_revision'],'status':'ready'}
        # Every returned exercise refers to its original row; it is never a
        # second assignment or a second student success/failure.
        for exercise in history['exercises']:
            if not exercise['retired'] and not exercise['archived']:
                original=access(conn,exercise['bank_id'])
                existing.append({**metadata,**exercise,'id':exercise['bank_id'],
                                 'math_type':original['math_type'],'year':original['year'],
                                 'number':original['number'],'student_access':original})
        if history['active_pending']:
            omitted['pending_existing']+=1
            continue
        if not include_history and (history['attempt_count'] or history['seen_solution']):
            omitted['attempted_or_solution_seen']+=1
            continue
        if internal:
            metadata.update(aliases=match['alternate_bank_ids'],bindings=match['analysis']['bindings'],
                            methods=match['analysis']['methods'],checkpoints=match['analysis']['checkpoints'],
                            fingerprint=match['analysis']['fingerprint'],history=history)
        else:
            # Search metadata never returns a solution, conditional constants,
            # resource paths or annotation reasoning, even for visible items.
            metadata['history']={k:history[k] for k in ('attempt_count','seen_question','seen_solution')}
        items.append(metadata)
    key=lambda item:hashlib.sha256(item['entity_id'].encode()).digest()
    items.sort(key=key);existing.sort(key=lambda item:(key(item),item['probe_id']))
    return {'catalog_revision':revision,'topic_ids':list(topic_ids),'offset':offset,'limit':limit,
            'total':len(items),'next_offset':offset+limit if offset+limit<len(items) else None,
            'items':items[offset:offset+limit],'existing_exercises':existing,
            'omitted':omitted,'include_history':include_history,'retrieval_mode':'prepared_atoms',
            'scope':'仅ready且材料/原子依赖有效；所有数学类别共同检索，确认同题去重，任一确认别名预留则整组排除。',
            'history_policy':'已有未完成练习沿原记录复用；过期计划先复核。做过或看过解析默认不作新检验；明确复习目的后可include_history。',
            'coverage_note':'未命中表示当前就绪标注没有符合项，不代表原始资料没有该类题。'}
