"""Report structure validation and read-only compatibility for older reports."""
import math


def text(value, default=''):
    return value if isinstance(value,str) else default


def report_issues(report):
    if not isinstance(report,dict):return ['report 必须是对象']
    errors=[]
    def string(obj,key,path='',nonempty=False):
        if not isinstance(obj.get(key),str) or nonempty and not obj[key].strip():errors.append(path+key)
    def array(obj,key,path=''):
        if not isinstance(obj.get(key),list):errors.append(path+key);return []
        return obj[key]
    for key in ('author','method','source_sha256','summary','score_status'):string(report,key,nonempty=True)
    expected=report.get('expected_count')
    if type(expected) is not int or not 1<=expected<=100:errors.append('expected_count（1–100 的整数）')
    questions=array(report,'questions')
    numbers=[str(q.get('number','')) for q in questions if isinstance(q,dict)]
    if type(expected) is int and 1<=expected<=100 and (len(numbers)!=expected or set(numbers)!={str(n) for n in range(1,expected+1)}):errors.append('questions 必须完整覆盖 expected_count 且题号唯一')
    if not questions:errors.append('questions 不能为空')
    array(report,'probes');array(report,'limitations')
    priorities=array(report,'priorities')
    for i,item in enumerate(priorities):
        if not isinstance(item,dict):errors.append(f'priorities[{i}]');continue
        for key in ('label','evidence','action'):string(item,key,f'priorities[{i}].')
    if isinstance(report.get('limitations'),list) and any(not isinstance(x,str) for x in report['limitations']):errors.append('limitations 必须为文字数组')
    for i,q in enumerate(questions):
        path=f'questions[{i}].'
        if not isinstance(q,dict):errors.append(path);continue
        for key in ('subject','stem','observation','reference_answer','reference_reasoning'):string(q,key,path)
        if 'knowledge' in q and (not isinstance(q['knowledge'],list) or any(not isinstance(v,str) for v in q['knowledge'])):errors.append(path+'knowledge')
        for key in ('max_score','score_earned'):
            value=q.get(key)
            if key not in q or value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0):errors.append(path+key)
        if q.get('correctness') not in ('correct','wrong','partial','unknown'):errors.append(path+'correctness')
        if not isinstance(q.get('fingerprint'),dict):errors.append(path+'fingerprint')
        regions=array(q,'regions',path)
        if not regions and not (q.get('evidence_status')=='missing' and q.get('correctness')=='unknown' and report.get('completion') in ('partial','needs_material')):
            errors.append(path+'regions 不能为空')
        for j,region in enumerate(regions):
            if not isinstance(region,dict) or type(region.get('page')) is not int or not isinstance(region.get('bbox'),list) or len(region['bbox'])!=4 or any(type(n) not in (int,float) or not math.isfinite(n) for n in region['bbox']):errors.append(path+f'regions[{j}]')
        for j,hypothesis in enumerate(array(q,'hypotheses',path)):
            if not isinstance(hypothesis,dict):errors.append(path+f'hypotheses[{j}]');continue
            for key in ('id','label','evidence','alternative','correction'):string(hypothesis,key,path+f'hypotheses[{j}].')
        for j,event in enumerate(array(q,'skill_events',path)):
            if not isinstance(event,dict):errors.append(path+f'skill_events[{j}]');continue
            for key in ('skill_id','label'):string(event,key,path+f'skill_events[{j}].',True)
            if event.get('kind') not in ('exam_error','exam_success','hypothesis','incomplete'):errors.append(path+f'skill_events[{j}].kind')
    return errors


def present_diagnosis(item):
    result=dict(item) if isinstance(item,dict) else {}
    for key in ('stem','observation','reference_answer','reference_reasoning','grading_note','cause_summary'):result[key]=text(result.get(key))
    guide=result.get('solution_guide')
    result['solution_guide']=({'entry_point':text(guide.get('entry_point')),
                              'strategy':text(guide.get('strategy')),
                              **{key:[v for v in guide.get(key,[]) if isinstance(v,str)]
                                 if isinstance(guide.get(key),list) else [] for key in ('key_steps','pitfalls')}}
                             if isinstance(guide,dict) else None)
    result['regions']=result.get('regions') if isinstance(result.get('regions'),list) else []
    result['fingerprint']=result.get('fingerprint') if isinstance(result.get('fingerprint'),dict) else {}
    result['knowledge']=[v for v in result.get('knowledge',[]) if isinstance(v,str) and v.strip()] if isinstance(result.get('knowledge'),list) else []
    hypotheses=result.get('hypotheses')
    result['hypotheses']=[]
    for i,h in enumerate(hypotheses if isinstance(hypotheses,list) else []):
        if not isinstance(h,dict):continue
        alternate=h.get('alternative',h.get('alternatives'))
        if isinstance(alternate,list):alternate='；'.join(x for x in alternate if isinstance(x,str))
        result['hypotheses'].append({**h,'id':text(h.get('id'),f'legacy-{i}'),
            'label':text(h.get('label'),text(h.get('cause'))),'evidence':text(h.get('evidence')),
            'alternative':text(alternate),'correction':text(h.get('correction')),'minimal_check':text(h.get('minimal_check'))})
    return result
