"""Rebuild a conservative learning profile from attributable saved evidence.

No Agent-written ability score is persisted. Grading changes to the same work
replace that interpretation; changed work retains its earlier independent form.
"""
import hashlib
import json


def parsed(value,default=None):
    try:return json.loads(value) if value else default
    except (ValueError,TypeError):return default


def material_revision(row):
    value=[row.get('response',''),parsed(row.get('images_json'),[]),parsed(row.get('image_roles_json'),{})]
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def _attempt_evidence(conn):
    history={}
    for row in conn.execute("SELECT record_id,payload,created_at FROM record_versions WHERE kind='attempt' ORDER BY created_at,rowid"):
        value=parsed(row['payload'],{})
        if isinstance(value,dict):history.setdefault(row['record_id'],[]).append(value)
    for row in conn.execute('''SELECT a.*,d.paper_id,d.question_id,d.skill_id,d.payload_json
        FROM probe_attempts a JOIN diagnostic_probes d ON d.id=a.probe_id
        JOIN papers p ON p.id=d.paper_id WHERE p.archived_at IS NULL ORDER BY a.created_at,a.rowid'''):
        current=dict(row);versions={}
        for value in history.get(row['id'],[])+[current]:
            versions[material_revision(value)]=value
        independent=None;assisted=None
        for revision,value in versions.items():
            assessment=parsed(value.get('assessment_json'),{})
            if not isinstance(assessment,dict) or assessment.get('method')=='explicit_answer_match':continue
            if type(assessment.get('correct')) is not bool:continue
            entry={**value,'revision':revision,'assessment':assessment}
            if value.get('answer_exposed'):assisted=entry
            else:independent=entry
        payload=parsed(row['payload_json'],{})
        for value,is_independent in ((independent,True),(assisted,False)):
            if not value:continue
            correct=value['assessment']['correct']
            yield {'id':row['id']+':'+value['revision'],'paper_id':row['paper_id'],
                   'question_id':row['question_id'],'probe_id':row['probe_id'],'attempt_id':row['id'],
                   'skill_id':row['skill_id'],'label':payload.get('skill_label') or row['skill_id'],
                   'kind':('probe_success' if correct else 'probe_failure') if is_independent else ('assisted_success' if correct else 'assisted_failure'),
                   'created_at':value.get('created_at') or row['created_at'],
                   'material_revision':value['revision'],'source':'attempt','independent':is_independent,
                   'observation':value['assessment'].get('feedback',''),
                   'assessment_result_id':value['assessment'].get('task_result_id'),
                   'detail':{'independent':is_independent,'answer_exposed':not is_independent,'attempt_id':row['id']}}


def build_profile(conn,*,temporal=True):
    grouped={}
    def skill(sid,label):return grouped.setdefault(sid,{'skill_id':sid,'label':label,'events':[],
                                                       'hypotheses':[],'probe_ids':[]})
    # Keep provisional observations traceable, but do not turn a pending or
    # legacy, unverified interpretation into a definite ability judgement.
    verified_reports={};report_contents={};verified_by_paper={}
    # Row order is the publication order. Appending another review must not
    # replace an already sufficient proof and invalidate unrelated evidence.
    for row in conn.execute('SELECT id,paper_id,report_json FROM agent_reports ORDER BY rowid'):
        report=parsed(row['report_json'],{})
        report_contents[row['id']]=report
        review=report.get('review') if isinstance(report,dict) else None
        verified_reports[row['id']]=(isinstance(report,dict)
            and isinstance(review,dict) and review.get('status')=='verified'
            and report.get('completion')=='complete')
        if verified_reports[row['id']] and report.get('revision',{}).get('kind')=='review_question':
            verified_by_paper.setdefault(row['paper_id'],[]).append((row['id'],report))
    def extends(report_id,source_id):
        seen=set()
        while isinstance(report_id,str) and report_id and report_id not in seen:
            if report_id==source_id:return True
            seen.add(report_id)
            revision=report_contents.get(report_id,{}).get('revision',{})
            report_id=revision.get('parent_report_id') if isinstance(revision,dict) else None
        return False
    scoped_verified={}
    for row in conn.execute('''SELECT q.id,q.paper_id,d.report_id,d.diagnosis_json FROM questions q
                              JOIN question_diagnoses d ON d.question_id=q.id'''):
        if verified_reports.get(row['report_id']):
            continue
        diagnosis=parsed(row['diagnosis_json'],{})
        saved=report_contents.get(row['report_id'],{})
        for report_id,report in verified_by_paper.get(row['paper_id'],[]):
            if (saved.get('source_sha256') and saved.get('source_sha256')==report.get('source_sha256') and
                    extends(report_id,row['report_id']) and
                    any(q==diagnosis for q in report.get('questions',[]))):
                # Certify identical evidence with its first valid publication;
                # retain the original event/report and never count it twice.
                scoped_verified[(row['id'],row['report_id'])]=report_id
                break
    facts={}
    for row in conn.execute('''SELECT e.*,p.exam_date,p.created_at AS paper_created_at FROM learning_events e
        JOIN papers p ON p.id=e.paper_id WHERE p.archived_at IS NULL
        AND e.kind IN ('exam_error','exam_success','hypothesis','incomplete') ORDER BY e.created_at,e.rowid'''):
        detail=parsed(row['detail_json'],{})
        value={**dict(row),'detail':detail,'source':'exam','independent':None,
               'verified':verified_reports.get(detail.get('report_id'),False) or
                          (row['question_id'],detail.get('report_id')) in scoped_verified,
               'verified_by_report_id':scoped_verified.get((row['question_id'],detail.get('report_id'))),
               'observation':detail.get('evidence',''),
               'created_at':row['exam_date'] or (row['paper_created_at'] if row['paper_created_at']!='now' else row['created_at'])}
        facts[(row['question_id'],row['skill_id'])]=value
    for value in facts.values():skill(value['skill_id'],value['label'])['events'].append(value)
    for value in _attempt_evidence(conn):skill(value['skill_id'],value['label'])['events'].append(value)
    for row in conn.execute('''SELECT q.id,q.paper_id,d.report_id,d.diagnosis_json FROM question_diagnoses d
        JOIN questions q ON q.id=d.question_id JOIN papers p ON p.id=q.paper_id WHERE p.archived_at IS NULL'''):
        diagnosis=parsed(row['diagnosis_json'],{})
        ids={e.get('skill_id'):e.get('label') for e in diagnosis.get('skill_events',[]) if e.get('skill_id')}
        for sid,label in ids.items():
            item=skill(sid,label or sid)
            item['hypotheses'].extend({'paper_id':row['paper_id'],'question_id':row['id'],
                'report_id':row['report_id'],'hypothesis':h} for h in diagnosis.get('hypotheses',[]))
    for row in conn.execute('''SELECT d.id,d.skill_id,d.payload_json FROM diagnostic_probes d JOIN papers p ON p.id=d.paper_id
        WHERE p.archived_at IS NULL AND d.id NOT IN (SELECT probe_id FROM retired_probes) ORDER BY d.created_at,d.id'''):
        payload=parsed(row['payload_json'],{})
        skill(row['skill_id'],payload.get('skill_label') or row['skill_id'])['probe_ids'].append(row['id'])
    for item in grouped.values():
        from app.learning.dates import project,groups,mixed
        if temporal:item['events']=project(conn,item['events'])
        events=[e for bucket in groups(item['events']) for e in sorted(bucket,key=lambda e:e['id'])] if temporal else sorted(item['events'],key=lambda e:(e['created_at'],e['source']=='attempt',e['id']))
        item['events']=events
        effective=[e for e in events if e['kind'] in ('exam_error','exam_success','probe_failure','probe_success')
                   and (e['source']!='exam' or e.get('verified'))]
        failures=[e for e in effective if e['kind'] in ('exam_error','probe_failure')]
        successes=[e for e in effective if e['kind'] in ('exam_success','probe_success')]
        item.update(failures=len(failures),successes=len(successes),
                    pending=sum(e['kind'] in ('hypothesis','incomplete') or
                                (e['source']=='exam' and not e.get('verified')) for e in events),
                    papers=len({e['paper_id'] for e in events}),
                    independent_probe_successes=sum(e['kind']=='probe_success' for e in effective),
                    assisted_successes=sum(e['kind']=='assisted_success' for e in events),
                    attempt_count=len({e['attempt_id'] for e in events if e.get('attempt_id')}))
        if not effective:
            item.update(state='未覆盖',state_reason='尚无足够的有效作答结论；待核对分析、猜测或材料不足不等于确定薄弱。')
        elif temporal and mixed(groups(effective)[-1]):
            item.update(state='巩固中',state_reason='同一时间范围内有对有错，还需要再练几道。')
        elif effective[-1]['kind'] in ('exam_error','probe_failure'):
            item.update(state='需要关注',state_reason='最近的有效作答仍有错误证据；解析后完成单独记录。')
        else:
            if temporal:
                ordered=groups(effective);last_error=max((i for i,b in enumerate(ordered) if any(e['kind'] in ('exam_error','probe_failure') for e in b)),default=-1)
                following=[e for b in ordered[last_error+1:] for e in b]
            else:
                last_error=max((i for i,e in enumerate(effective) if e['kind'] in ('exam_error','probe_failure')),default=-1)
                following=[e for e in effective[last_error+1:] if e['kind'] in ('exam_success','probe_success')]
            diverse=len({e['paper_id'] for e in following})>=2 or len({e['created_at'][:10] for e in following})>=2
            if len(following)>=2 and diverse:
                item.update(state='初步掌握',state_reason='最近错误之后，已有跨卷或不同日期的两次有效成功；仅适用于已记录的环节。')
            else:
                item.update(state='巩固中',state_reason='已有有效成功，仍需跨卷或间隔检验；一次答对不代表整个考点掌握。')
    return sorted(grouped.values(),key=lambda x:({'需要关注':0,'巩固中':1,'未覆盖':2,'初步掌握':3}[x['state']],x['label']))
