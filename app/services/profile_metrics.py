"""Readable rankings from saved answers, never generated ability scores."""
from app.learning.dates import recent,groups,mixed
from datetime import timedelta

STAGES={'entry':'切入','modeling':'建模','formula':'公式','calculation':'计算','finalization':'最终处理'}

def loss(diagnosis,row):
    maximum=diagnosis.get('max_score');earned=diagnosis.get('score_earned')
    import math
    if maximum is None or earned is None:return dict(max_score=maximum,score_earned=earned,lost_points=None,loss_basis=None,loss_unavailable_reason='missing_score')
    good=lambda x:type(x) in (int,float) and math.isfinite(x)
    if not good(maximum) or not good(earned) or maximum<=0 or earned<0 or earned>maximum:return dict(max_score=None,score_earned=None,lost_points=None,loss_basis=None,loss_unavailable_reason='invalid_score')
    if diagnosis.get('correctness') in ('wrong','partial') and maximum==earned:return dict(max_score=maximum,score_earned=earned,lost_points=None,loss_basis=None,loss_unavailable_reason='score_conflict')
    return dict(max_score=maximum,score_earned=earned,lost_points=maximum-earned,loss_basis='saved_estimate',loss_unavailable_reason=None)

def evidence(f):
    keys=('source','practice_source','paper_id','question_id','question_number','practice_id','attempt_id','bank_id','batch_id','label','occurred_at','answer_exposed','topic_ids','exam_date','exam_date_precision','exam_date_unknown_reason','max_score','score_earned','lost_points','loss_basis','loss_unavailable_reason')
    return dict(**{k:f.get(k) for k in keys},first_error_stage=(f.get('first_error') or {}).get('stage'),first_error_evidence=(f.get('first_error') or {}).get('evidence'))

def counts(fs):
    exams={f['question_id']:f for f in fs if f['source']=='exam'};known=[f for f in exams.values() if f['lost_points'] is not None]
    return dict(lost_points=sum(f['lost_points'] for f in known) if known else None if exams else 0,
        loss_known_question_count=len(known),loss_unknown_question_count=len(exams)-len(known),exam_failure_count=len(exams),practice_failure_count=sum(f['source']!='exam' for f in fs))

def weak_spots(data):
    nodes=data['nodes'];clock=data['clock'];spots=[]
    for n in nodes.values():
        if n['kind'] not in ('chapter','topic'):continue
        if n['kind']=='topic':
            parent=n['parent_id'];nested=False
            while parent in nodes:
                if nodes[parent]['kind'] in ('chapter','topic'):nested=True;break
                parent=nodes[parent]['parent_id']
            if nested:continue
        judged=[f for f in data['node_facts'][n['id']] if f.get('counted',True) and f['correct'] is not None and f['independent'] is not False]
        buckets=groups([dict(id=f['id'],created_at=f['occurred_at'] or '',kind='probe_success' if f['correct'] else 'probe_failure',fact=f) for f in judged])
        if not buckets or not n['distribution']['weak'] and not mixed(buckets[-1]):continue
        failures=[f for f in judged if f['correct'] is False];fresh=[f for f in failures if recent(f['occurred_at'],clock)];history=[f for f in failures if f not in fresh]
        period='recent' if fresh else 'historical';selected=fresh or history
        selected.sort(key=lambda f:f['occurred_at'] or '',reverse=True)
        ev=[evidence(f) for f in selected[:3]];rc=counts(fresh);hc=counts(history)
        stages=list(dict.fromkeys(STAGES[e['first_error_stage']] for e in ev if e['first_error_stage'] in STAGES))
        total=sum(recent(f['occurred_at'],clock) for f in judged) if fresh else len(judged)
        basis=f'{"近28天" if fresh else "历史记录中"}做了{total}道，错{len(selected)}道。'
        if ev:basis+='例：'+'、'.join(e['label'] for e in ev)+('；最先出错的环节：'+'、'.join(stages) if stages else '')+'。'
        spots.append(dict(node_id=n['id'],name=n['name'],kind=n['kind'],subject_id=n['parent_id'],weak_atom_count=n['distribution']['weak'],
            observed_atom_count=sum(nodes[a]['display_state']!='no_record' for a in data['descendants'][n['id']]),total_atom_count=len(data['descendants'][n['id']]),
            recent_failures=len(fresh),recent_judged=sum(recent(f['occurred_at'],clock) for f in judged),historical_failures=len(history),
            failure_ratio=len(selected)/max(1,total),window={'from':(clock-timedelta(days=27)).date().isoformat(),'to':clock.date().isoformat()},
            basis=basis,evidence=ev,evidence_period=period,period_explanation='近28天的做题记录' if fresh else '最近记录不多，用历史错题补充；不表示最近又做错了。',
            loss_attribution='related_question_loss',loss_basis='saved_estimate' if any(f.get('lost_points') is not None for f in selected if f['source']=='exam') else None,
            **{'recent_'+k:v for k,v in rc.items()},**{'historical_'+k:v for k,v in hc.items()}))
    def key(s):
        p='recent' if s['evidence_period']=='recent' else 'historical'
        return (p!='recent',-(s[p+'_lost_points'] or 0),-s[p+'_exam_failure_count'],-s[p+'_practice_failure_count'],-s['failure_ratio'],-s['weak_atom_count'],s['node_id'])
    return sorted(spots,key=key)

def first_error_summary(data):
    fs=[f for f in data['facts'] if f.get('counted',True) and f['correct'] is False and f['independent'] is not False and recent(f['occurred_at'],data['clock'])]
    stages={s:[] for s in STAGES}
    for f in fs:
        e=f.get('first_error') or {}
        if e.get('stage') in stages and e.get('evidence','').strip():stages[e['stage']].append(f)
    counts=sorted(((s,len(v)) for s,v in stages.items()),key=lambda p:(-p[1],p[0]));stage,n=counts[0]
    attributed=sum(len(v) for v in stages.values())
    if len(fs)<5 or attributed<3 or n<3 or n*2<len(fs) or counts[1][1]==n:return None
    return dict(period='recent',window={'from':(data['clock']-timedelta(days=27)).date().isoformat(),'to':data['clock'].date().isoformat()},wrong_count=len(fs),attributed_count=attributed,unattributed_count=len(fs)-attributed,
        stages=[dict(stage=s,count=c) for s,c in counts],dominant_stage=stage,dominant_count=n,statement=f'近期{len(fs)}道错题中，{n}道的首错记录在{STAGES[stage]}环节。',evidence=[evidence(f) for f in stages[stage][:3]])
