"""Compact evidence-based overview; atom detail and trends are lazy resources."""
from copy import deepcopy
from datetime import datetime,timedelta
import json
from threading import RLock
from app.common import json_load
from app.errors import ServiceError
from app.bank.access import preferences,policy_group
from app.bank.originals import uploaded_originals
from app.knowledge import catalog
from app.learning import feedback

STATES={'初步掌握':'mastered','巩固中':'learning','需要关注':'weak','证据不足':'no_record','未覆盖':'no_record'}
FIELDS=('attempts','correct','independent_correct','assisted_correct','independence_unknown_correct','wrong','unjudged','pending_grading')

def now():return datetime.now().astimezone()

def dated(value,tz):
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
    except (ValueError,TypeError,AttributeError):return None

def count(facts):
    result=dict.fromkeys(FIELDS,0)
    for f in facts:
        if not f.get('counted',True):continue
        result['attempts']+=1
        correct=f['correct']
        result['correct' if correct is True else 'wrong' if correct is False else 'unjudged']+=1
        if correct is True:
            result['independent_correct' if f['independent'] is True else 'assisted_correct' if f['independent'] is False else 'independence_unknown_correct']+=1
        if f['pending']:result['pending_grading']+=1
    return result

def distribution(nodes):
    result=dict.fromkeys(('mastered','learning','weak','no_record'),0)
    for n in nodes:result[n['display_state']]+=1
    return result


def state_reason(node):
    return {'需要关注':'最近做的题还有出错，建议再练几道。','巩固中':'已经做对过，换几道题再试试。',
            '初步掌握':'在不同试卷或不同日期做对过，继续练习保持。',
            '未覆盖':'还没有这部分的做题记录。','证据不足':'记录还不够，再做几道才能判断。'}[node['state']]

def _assessment_time(conn,assessment,fallback):
    rid=(assessment or {}).get('task_result_id')
    row=conn.execute('SELECT created_at FROM learning_results WHERE id=?',(rid,)).fetchone() if rid else None
    return row[0] if row else fallback

def facts(conn):
    values=[]
    for row in conn.execute('''SELECT q.*,p.title,p.exam_date,p.created_at paper_created,d.diagnosis_json,r.report_json
        FROM questions q JOIN papers p ON p.id=q.paper_id JOIN question_diagnoses d ON d.question_id=q.id
        JOIN agent_reports r ON r.id=d.report_id WHERE p.archived_at IS NULL'''):
        diagnosis=json.loads(row['diagnosis_json']);report=json.loads(row['report_json'])
        evidence=diagnosis.get('answer_evidence') or {}
        verified=report.get('review',{}).get('status')=='verified' and report.get('completion')=='complete'
        correctness=diagnosis.get('correctness','unknown')
        values.append(dict(source='exam',practice_source=None,id=row['id'],question_id=row['id'],practice_id=None,
            attempt_id=None,paper_id=row['paper_id'],question_number=str(row['number']),bank_id=row['match_bank_id'],batch_id=None,label=f"{row['title']} 第{row['number']}题",
            occurred_at=row['exam_date'] or row['paper_created'],correct=(True if correctness=='correct' else False if correctness in ('wrong','partial') else None) if verified else None,
            independent=None,answer_exposed=None,pending=False,assessment=None,first_error=diagnosis.get('first_error'),
            counted=evidence.get('student_state')=='visible' and bool(evidence.get('student_work','').strip()),needs_review=correctness=='unknown'))
    for row in conn.execute('''SELECT a.*,d.paper_id,d.question_id,d.bank_id,p.title FROM probe_attempts a
        JOIN diagnostic_probes d ON d.id=a.probe_id JOIN papers p ON p.id=d.paper_id WHERE p.archived_at IS NULL'''):
        assessment=feedback.effective(row['assessment_json'])
        values.append(dict(source='practice',practice_source='paper_practice',id=row['id'],attempt_id=row['id'],practice_id=row['probe_id'],
            paper_id=row['paper_id'],question_id=row['question_id'],bank_id=row['bank_id'],batch_id=None,label=row['title']+' · 练习',
            occurred_at=row['created_at'],correct=(assessment or {}).get('correct'),independent=not bool(row['answer_exposed']),answer_exposed=bool(row['answer_exposed']),
            pending=assessment is None,assessment=assessment,assessed_at=_assessment_time(conn,assessment,row['created_at']),
            first_error=(assessment or {}).get('first_error'),needs_review=bool(assessment and assessment.get('correct') is None)))
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'free_practice_attempts' in tables:
        for row in conn.execute('SELECT * FROM free_practice_attempts'):
            assessment=feedback.effective(row['assessment_json']);snap=json.loads(row['snapshot_json'])
            values.append(dict(source='free_practice',practice_source=None,id=row['id'],attempt_id=row['id'],practice_id=None,
                paper_id=None,question_id=None,bank_id=row['bank_id'],batch_id=None,label='自由练习',topic_ids=(assessment or {}).get('topic_ids',[]),
                occurred_at=row['created_at'],correct=(assessment or {}).get('correct'),independent=not bool(row['answer_exposed']),answer_exposed=bool(row['answer_exposed']),
                pending=assessment is None,assessment=assessment,assessed_at=_assessment_time(conn,assessment,row['created_at']),
                first_error=(assessment or {}).get('first_error'),needs_review=bool(assessment and assessment.get('correct') is None)))
    if 'profile_practice_attempts' in tables:
        for row in conn.execute('''SELECT a.*,e.batch_id,e.bank_id,e.topic_ids_json FROM profile_practice_attempts a
            JOIN profile_practice_exercises e ON e.id=a.exercise_id'''):
            assessment=feedback.effective(row['assessment_json'])
            values.append(dict(source='practice',practice_source='profile_practice',id=row['id'],attempt_id=row['id'],practice_id=row['exercise_id'],
                paper_id=None,question_id=None,bank_id=row['bank_id'],batch_id=row['batch_id'],label='画像选题',topic_ids=(assessment or {}).get('topic_ids',[]),
                occurred_at=row['created_at'],correct=(assessment or {}).get('correct'),independent=not bool(row['answer_exposed']),answer_exposed=bool(row['answer_exposed']),
                pending=assessment is None,assessment=assessment,assessed_at=_assessment_time(conn,assessment,row['created_at']),first_error=(assessment or {}).get('first_error'),
                needs_review=bool(assessment and assessment.get('correct') is None)))
    for value in values:value.setdefault('question_number',None)
    return values


class ProfileService:
    def __init__(self,rt):self.rt=rt;self.lock=RLock();self.key=None;self.value=None

    def data(self):
        with self.lock:
            clock=now();key=(self.rt.workspace.revision(),clock.date().isoformat())
            if self.key==key and self.value is not None:return self.value
            snapshot=self.rt.frontend._knowledge();navigation=self.rt.frontend._navigation()
            with self.rt.database.session() as conn:
                prefs=preferences(conn);fs=facts(conn);release=catalog.active_id(conn)
                by_id={f['id']:f for f in fs}
                for f in fs:f.setdefault('topic_ids',[])
                for node in snapshot['nodes']:
                    for event in node['events']:
                        f=by_id.get(event['question_id'] if event['source']=='exam' else event.get('attempt_id'))
                        if f and node['skill_id'] not in f['topic_ids']:f['topic_ids'].append(node['skill_id'])
                receipts=[]
                for f in fs:
                    if f['assessment']:
                        source=f['practice_source'] or f['source']
                        state=feedback.info(conn,source,f['attempt_id'],f['assessment'])
                        receipts.append(dict(source=source,attempt_id=f['attempt_id'],practice_id=f['practice_id'],paper_id=f['paper_id'],
                            bank_id=f['bank_id'],batch_id=f['batch_id'],title=f['label'],assessed_at=f['assessed_at'],correct=f['correct'],
                            feedback_revision=state['feedback_revision'],unread=state['feedback_unread'],read_at=state['feedback_read_at']))
                originals=uploaded_originals(conn);excluded=set(originals)
                excluded.update(r[0] for r in conn.execute('SELECT bank_id FROM bank_views'))
                excluded.update(r[0] for r in conn.execute('SELECT bank_id FROM diagnostic_probes'))
                excluded.update(r[0] for r in conn.execute('SELECT bank_id FROM profile_practice_exercises'))
                excluded.update(f['bank_id'] for f in fs if f['bank_id'])
                reserved={(v['math_type'],str(v['year'])) for v in prefs['reserved']}
                excluded.update(r['bank_id'] for r in conn.execute('SELECT * FROM bank_identity') if (r['math_type'],str(r['year'])) in reserved)
                blocked=set()
                for bid in excluded:blocked.update(policy_group(conn,bid))
                cards=self.rt.frontend._cards(conn,include_access=False)
                pending_papers=conn.execute('''SELECT count(*) FROM papers p WHERE p.archived_at IS NULL
                    AND EXISTS(SELECT 1 FROM questions q WHERE q.paper_id=p.id)
                    AND NOT EXISTS(SELECT 1 FROM agent_reports r WHERE r.paper_id=p.id)
                    AND NOT EXISTS(SELECT 1 FROM workflow_jobs j WHERE j.paper_id=p.id AND j.kind='analyze_paper' AND j.status IN ('queued','dispatching','running'))''').fetchone()[0]
                issues=conn.execute('''SELECT count(*) FROM papers p WHERE p.archived_at IS NULL AND EXISTS(
                    SELECT 1 FROM agent_reports r WHERE r.id=(SELECT id FROM agent_reports WHERE paper_id=p.id ORDER BY rowid DESC LIMIT 1)
                    AND json_extract(r.report_json,'$.review.status')='needs_review')''').fetchone()[0]
            operational=fs
            fs=[f for f in fs if prefs.get('include_free_practice',True) or f['source']!='free_practice']
            raw={n['skill_id']:n for n in snapshot['nodes']};nodes={};descendants={}
            for tid,n in raw.items():
                descendants[tid]=set()
                nodes[tid]=dict(id=tid,parent_id=n['parent_id'],name=n['label'],kind=n['origin'].get('node_kind') or ('atom' if n['scope_level']=='concept' else n['scope_level']),
                    math_types=n['origin'].get('math_types',[1,2,3]),state=n['state'],state_reason=state_reason(n),display_state=STATES[n['state']],
                    successes=n['successes'],failures=n['failures'],assisted=n['assisted_successes'],pending=n['pending'],
                    last_attempt_at=max((e['created_at'] for e in n['events']),default=None),ready_question_count=0,study_ready_question_count=0,selectable_question_count=0)
            applicable={tid for tid,n in nodes.items() if n['kind']=='atom' and (not n['math_types'] or prefs['study_type'] is None or prefs['study_type'] in n['math_types'])}
            for tid in applicable:
                cursor=tid;seen=set()
                while cursor in nodes and cursor not in seen:
                    seen.add(cursor);descendants[cursor].add(tid);cursor=nodes[cursor]['parent_id']
            ready={tid:set() for tid in nodes};study={tid:set() for tid in nodes};selectable={tid:set() for tid in nodes}
            for b in navigation['bank']:
                if b['status']!='ready':continue
                for binding in b['topics']:
                    cursor=binding['topic_id'];seen=set()
                    while cursor in nodes and cursor not in seen:
                        seen.add(cursor);ready[cursor].add(b['bank_id'])
                        if prefs['study_type'] is None or prefs['study_type'] in b['math_types']:study[cursor].add(b['bank_id'])
                        if b['bank_id'] not in blocked:selectable[cursor].add(b['bank_id'])
                        cursor=nodes[cursor]['parent_id']
            node_facts={}
            for tid,n in nodes.items():
                observed=[f for f in fs if set(f['topic_ids']) & (descendants[tid]|{tid})]
                node_facts[tid]=observed
                n['distribution']=distribution(nodes[a] for a in descendants[tid])
                n.update(ready_question_count=len(ready[tid]),study_ready_question_count=len(study[tid]),selectable_question_count=len(selectable[tid]))
                if n['kind']!='atom':
                    n.update(successes=sum(f['correct'] is True and f['independent'] is not False for f in observed),failures=sum(f['correct'] is False and f['independent'] is not False for f in observed),assisted=sum(f['correct'] is True and f['independent'] is False for f in observed))
                    n['last_attempt_at']=max((f['occurred_at'] for f in observed if f['occurred_at']),default=None)
            result=dict(clock=clock,generated_at=clock.isoformat(),prefs=prefs,release=release,facts=fs,nodes=nodes,descendants=descendants,
                node_facts=node_facts,receipts=receipts,pending_papers=pending_papers,issues=issues,cards=cards,snapshot=snapshot,operational_facts=operational)
            self.value=result;self.key=key if key==(self.rt.workspace.revision(),now().date().isoformat()) else None
            return result

    def atoms(self,tid,offset=0,limit=60):
        data=self.data();nodes=data['nodes']
        if tid not in nodes:raise ServiceError('考点不存在',404)
        from app.services.frontend_reads import page
        return dict(page([deepcopy(n) for k,n in nodes.items() if k in data['descendants'][tid]],offset,limit),node={k:nodes[tid][k] for k in ('id','name','kind')})

    def trends(self,weeks=12):
        if type(weeks) is not int or not 1<=weeks<=52:raise ValueError('weeks须为1–52')
        d=self.data();clock=d['clock'];monday=clock.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=clock.weekday())
        start=monday-timedelta(weeks=weeks-1);weekly=[];period=[];undated=[]
        for f in d['facts']:
            dt=dated(f['occurred_at'],clock.tzinfo)
            if dt is None:undated.append(f)
            elif start<=dt<=clock:period.append(f)
        for i in range(weeks):
            a=start+timedelta(weeks=i);b=a+timedelta(weeks=1)
            rows=[f for f in period if a<=dated(f['occurred_at'],clock.tzinfo)<b]
            weekly.append(dict(week_start=a.date().isoformat(),week_end=(b-timedelta(days=1)).date().isoformat(),complete=b<=clock,
                sources={s:count(f for f in rows if f['source']==s) for s in ('exam','practice','free_practice')}))
        return dict(generated_at=d['generated_at'],timezone=clock.strftime('%z'),include_free_practice=d['prefs']['include_free_practice'],
            period={'from':start.isoformat(),'to':clock.isoformat(),'weeks':weeks,'week_starts_on':'monday'},weekly=weekly,totals=count(period),undated=count(undated),limitations=self.limitations(d))

    def limitations(self,d):
        values=[]
        if not d['release']:values.append('考点目录还没准备好，暂时看不到的部分不代表你不会。')
        if d['snapshot']['pending_sources']:values.append('还有一些作答没整理到考点里，这里的统计还不完整。')
        if any(f['source']=='exam' and f['independent'] is None for f in d['facts']):values.append('无法确认原卷是否独立完成，所以没计入独立做对。没填作答日期的卷子，目前按上传日期统计。')
        return values

    def targets(self,d,subject=None,chapter=None):
        nodes=d['nodes'];allowed=set(nodes)
        for tid,kind in ((subject,'subject'),(chapter,'chapter')):
            if tid:
                if tid not in nodes:raise ServiceError('目录节点不存在',404)
                if nodes[tid]['kind']!=kind:raise ValueError('范围节点类型不合法')
                allowed &= d['descendants'][tid]
        if subject and chapter and not d['descendants'][chapter].issubset(d['descendants'][subject]):raise ValueError('章不属于指定科目')
        result=[]
        for tid,n in nodes.items():
            if tid not in allowed or n['kind']!='atom' or not n['selectable_question_count']:continue
            if n['math_types'] and d['prefs']['study_type'] and d['prefs']['study_type'] not in n['math_types']:continue
            observed=d['node_facts'][tid];dt=dated(n['last_attempt_at'],d['clock'].tzinfo)
            if n['display_state']=='weak':category='weak'
            elif n['assisted'] and not n['successes'] or dt and d['clock']-dt>=timedelta(days=14):category='review_due'
            elif not observed and not n['pending'] and n['study_ready_question_count']:category='uncovered'
            else:continue
            result.append(dict(topic_id=tid,name=n['name'],category=category,reason=n['state_reason']))
        return result

    def overview(self):
        d=self.data();clock=d['clock'];nodes=d['nodes'];monday=clock.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=clock.weekday())
        week=[f for f in d['facts'] if dated(f['occurred_at'],clock.tzinfo) and monday<=dated(f['occurred_at'],clock.tzinfo)<=clock]
        subjects=[]
        for n in nodes.values():
            if n['kind']=='subject':subjects.append(dict(n,chapters=[deepcopy(c) for c in nodes.values() if c['kind']=='chapter' and c['parent_id']==n['id']]))
        spots=[];window=clock-timedelta(days=28)
        for n in nodes.values():
            if n['kind'] not in ('chapter','topic') or not n['distribution']['weak']:continue
            if n['kind']=='topic':
                cursor=n['parent_id'];seen=set();nested=False
                while cursor in nodes and cursor not in seen:
                    seen.add(cursor)
                    if nodes[cursor]['kind'] in ('chapter','topic'):nested=True;break
                    cursor=nodes[cursor]['parent_id']
                if nested:continue
            recent=[f for f in d['node_facts'][n['id']] if f['correct'] is not None and f['independent'] is not False and dated(f['occurred_at'],clock.tzinfo) and window<=dated(f['occurred_at'],clock.tzinfo)<=clock]
            failures=[f for f in recent if f['correct'] is False]
            if not failures:continue
            failures.sort(key=lambda f:f['occurred_at'],reverse=True)
            evidence=[dict(**{k:f[k] for k in ('source','paper_id','question_id','question_number','practice_id','attempt_id','bank_id','label','occurred_at')},
                first_error_stage=(f['first_error'] or {}).get('stage'),first_error_evidence=(f['first_error'] or {}).get('evidence')) for f in failures[:3]]
            stage_names={'entry':'切入','modeling':'建模','formula':'公式','calculation':'计算','finalization':'最终处理'}
            stages=list(dict.fromkeys(stage_names[e['first_error_stage']] for e in evidence if e['first_error_stage'] in stage_names))
            basis=(f'近28天做了{len(recent)}道，错{len(failures)}道。例：'+'、'.join(e['label'] for e in evidence)+('；最先出错的环节：'+'、'.join(stages) if stages else '')+'。') if evidence else None
            spots.append(dict(node_id=n['id'],name=n['name'],kind=n['kind'],subject_id=n['parent_id'],weak_atom_count=n['distribution']['weak'],
                observed_atom_count=sum(nodes[a]['display_state']!='no_record' for a in d['descendants'][n['id']]),total_atom_count=len(d['descendants'][n['id']]),
                recent_failures=len(failures),recent_judged=len(recent),failure_ratio=len(failures)/len(recent),window={'from':window.isoformat(),'to':clock.isoformat()},
                basis=basis,evidence=evidence))
        spots.sort(key=lambda s:s['evidence'][0]['occurred_at'] or '',reverse=True)
        spots.sort(key=lambda s:(-s['recent_failures'],-s['failure_ratio'],-s['weak_atom_count']))
        def conclusion(n):
            fs=d['node_facts'][n['id']];judged=[f for f in fs if f['correct'] is not None and f['independent'] is not False]
            return dict(node_id=n['id'],name=n['name'],subject_id=n['parent_id'],basis=f'已批改的{len(judged)}道题里，做对{sum(f["correct"] is True for f in judged)}道、错{sum(f["correct"] is False for f in judged)}道；只说明这些做过的题，不能代表整章都会。',judged_count=len(judged),successes=sum(f['correct'] is True for f in judged),failures=sum(f['correct'] is False for f in judged),
                independent_correct=sum(f['correct'] is True and f['independent'] is True for f in judged),observed_atom_count=sum(bool(d['node_facts'][a]) for a in d['descendants'][n['id']]),total_atom_count=len(d['descendants'][n['id']]),weak_atom_count=n['distribution']['weak'],last_attempt_at=n['last_attempt_at'])
        strong=[]
        for n in nodes.values():
            if n['kind']!='chapter':continue
            c=conclusion(n);dates={f['occurred_at'][:10] for f in d['node_facts'][n['id']] if f['occurred_at'] and f['correct'] is not None}
            if c['judged_count']>=5 and len(dates)>=2 and c['observed_atom_count']>=min(2,c['total_atom_count']) and not c['weak_atom_count'] and c['successes']:strong.append(c)
        strong.sort(key=lambda c:(c['failures']/c['judged_count'],-c['independent_correct'],-c['observed_atom_count']/max(1,c['total_atom_count']),c['node_id']))
        weak=next((conclusion(nodes[s['node_id']]) for s in spots if s['kind']=='chapter' and s['recent_failures']>=2 and conclusion(nodes[s['node_id']])['judged_count']>=3),None)
        windows=[]
        for a,b in ((monday-timedelta(weeks=8),monday-timedelta(weeks=4)),(monday-timedelta(weeks=4),monday)):
            fs=[f for f in d['facts'] if f['independent'] is True and f['correct'] is not None and dated(f['occurred_at'],clock.tzinfo) and a<=dated(f['occurred_at'],clock.tzinfo)<b]
            windows.append(dict(independent_judged=len(fs),independent_correct=sum(f['correct'] is True for f in fs),**{'from':a.isoformat(),'to':b.isoformat()}))
        comparison=dict(previous=windows[0],current=windows[1],delta=windows[1]['independent_correct']-windows[0]['independent_correct'],basis='这里只比较独立做对了几道，不说明水平一定提高或下降。') if all(w['independent_judged'] for w in windows) else None
        targets=self.targets(d) if d['prefs']['study_type'] else [];counts={k:sum(t['category']==k for t in targets) for k in ('weak','review_due','uncovered')}
        unfinished=sum(c['status'] in ('pending','needs_supplement') for c in d['cards'])
        receipts=sorted(d['receipts'],key=lambda r:r['assessed_at'] or '',reverse=True);receipts.sort(key=lambda r:not r['unread'])
        review=[f for f in d['operational_facts'] if f['needs_review']];unread=sum(r['unread'] for r in receipts)
        next_steps=[dict(kind=k,available=bool(n),count=n,reason=reason,target=dict(paper_id=None,practice_id=None)) for k,n,reason in (
            ('read_feedback',unread,'查看新的批改反馈'),('review_results',len(review),'核对已有判断或补充材料'),('continue_practice',unfinished,'继续未完成练习'),('analyze_paper',d['pending_papers'],'核对切题后开始新卷分析'),('profile_batch',len(targets),'按已有画像选择一组练习'))]
        week_counts=count(week)
        visible_atoms=set().union(*(d['descendants'][s['id']] for s in subjects)) if subjects else set()
        return dict(generated_at=d['generated_at'],study_type=d['prefs']['study_type'],timezone=clock.strftime('%z'),week={'from':monday.isoformat(),'to':clock.isoformat(),'week_starts_on':'monday'},
            catalog_release_id=d['release'],include_free_practice=d['prefs']['include_free_practice'],home_stats=dict(attempts_this_week=week_counts['attempts'],independent_correct_this_week=week_counts['independent_correct'],grading_count=sum(f['pending'] for f in d['operational_facts'])),
            totals=dict(pending_analysis_paper_count=d['pending_papers'],unfinished_practice_count=unfinished,unread_feedback_count=unread,needs_review_count=len(review)),
            distribution=distribution(n for n in nodes.values() if n['kind']=='atom' and n['id'] in visible_atoms),
            subjects=subjects,weak_spots=spots[:5],conclusions=dict(strongest_chapter=strong[0] if strong else None,weakest_chapter=weak,independent_correct_comparison=comparison,
                unavailable_reasons=dict(strongest_chapter=None if strong else '记录还不够，再做几道才能判断。',weakest_chapter=None if weak else '最近的错题还不够，暂时不能判断哪章最弱。',independent_correct_comparison=None if comparison else '前后各四周里，能确认独立完成并批改过的题还不够。')),
            feedback=dict(unread_count=unread,recent_items=receipts[:3]),review=dict(total=len(review),counts={k:sum(f['source']==s for f in review) for k,s in [('exam_questions','exam'),('practice_attempts','practice'),('free_practice_attempts','free_practice')]},paper_issue_count=d['issues'],items=[dict(**{k:f[k] for k in ('source','question_id','attempt_id','practice_id','paper_id','bank_id')},reason='已有判断不确定或需补材料') for f in review[:5]]),
            recent_mistakes=[{k:f[k] for k in ('source','practice_source','question_id','question_number','practice_id','attempt_id','paper_id','bank_id','batch_id','label','occurred_at','answer_exposed','topic_ids')} for f in sorted(d['facts'],key=lambda f:f['occurred_at'] or '',reverse=True) if f['correct'] is False][:3],
            next_steps=next_steps,profile_batch_eligibility=dict(can_create=bool(targets),reason=None if targets else '请先选择数一、数二或数三；如果已经选好，暂时没有适合你这次练的题。',target_counts=counts),limitations=self.limitations(d))
