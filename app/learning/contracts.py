"""Versioned JSON Schema contracts for scoped paper learning tasks."""
from __future__ import annotations

import json
from jsonschema import Draft202012Validator

VERSION = '1.6'
PREPARATION_KINDS = ('maintain_catalog', 'annotate_questions')
KINDS = ('analyze_paper', 'review_question', 'prepare_practice', 'grade_attempt', 'summarize_paper', 'organize_knowledge', 'review_practice') + PREPARATION_KINDS
STAGES = ('entry', 'modeling', 'formula', 'calculation', 'finalization', 'unknown')


def string(*, nonempty=False, limit=16000):
    return {'type': 'string', 'minLength': int(nonempty), 'maxLength': limit}


def array(items, *, minimum=0, maximum=200, unique=False):
    return {'type': 'array', 'items': items, 'minItems': minimum,
            'maxItems': maximum, **({'uniqueItems': True} if unique else {})}


def obj(fields, *, optional=()):
    return {'type': 'object', 'properties': fields,
            'required': [k for k in fields if k not in optional], 'additionalProperties': False}


ID = {'type': 'string', 'pattern': r'^[A-Za-z0-9][A-Za-z0-9:._-]{0,199}$'}
SHA = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
TEXTS = array(string(), maximum=100)
IDS = array(ID, unique=True, maximum=100)
STAGE = {'enum': list(STAGES)}
ERROR = {'anyOf': [{'type': 'null'}, obj({'stage': STAGE, 'step': string(nonempty=True),
                                        'evidence': string(nonempty=True)})]}
REGION = obj({'page': {'type': 'integer', 'minimum': 1},
              'bbox': array({'type': 'number'}, minimum=4, maximum=4),
              'role': {'enum': ['question', 'work', 'marking', 'question_and_work', 'supplemental_work']}})
HYPOTHESIS = obj({'id': ID, 'label': string(nonempty=True), 'evidence': string(),
                  'alternative': string(), 'correction': string()})
FINGERPRINT = obj({'conditions': TEXTS, 'goal': string(), 'methods': TEXTS, 'operations': TEXTS})
SCORE = {'type': ['number', 'null'], 'minimum': 0}
EVENT = obj({'skill_id': ID, 'label': string(nonempty=True),
             'kind': {'enum': ['exam_error', 'exam_success', 'hypothesis', 'incomplete']}})
ANSWER_EVIDENCE = obj({'student_work': string(),
                      'student_state': {'enum':['visible','not_attempted','unreadable']},
                      'marking': {'enum':['none','correct','wrong','unclear']},
                      'marking_note': string()})
REVIEW = obj({'status': {'enum':['verified','needs_review']}, 'issues': TEXTS})
SOLUTION_GUIDE = obj({'entry_point': string(nonempty=True), 'strategy': string(nonempty=True),
                      'key_steps': array(string(nonempty=True), minimum=1, maximum=12),
                      'pitfalls': array(string(nonempty=True), minimum=1, maximum=8)})
QUESTION = obj({'number': {'type': 'integer', 'minimum': 1, 'maximum': 100},
                'subject': string(nonempty=True, limit=40), 'stem': string(),
                'max_score': SCORE, 'score_earned': SCORE,
                'correctness': {'enum': ['correct', 'wrong', 'partial', 'unknown']},
                'regions': array(REGION, maximum=30),
                'evidence_status': {'enum': ['readable', 'unclear', 'missing']},
                'reference_answer': string(), 'reference_reasoning': string(),
                'observation': string(), 'correct_parts': TEXTS, 'first_error': ERROR,
                'knowledge': TEXTS, 'fingerprint': FINGERPRINT,
                'hypotheses': array(HYPOTHESIS, maximum=10), 'skill_events': array(EVENT, maximum=30),
                'answer_evidence': ANSWER_EVIDENCE,
                'solution_guide': {'anyOf':[{'type':'null'},SOLUTION_GUIDE]},
                'cause_summary': string()},optional=('answer_evidence','solution_guide','cause_summary'))
QUESTION['properties']['correctness']['description']='作答可辨时对照给定参考判定；unknown仅用于作答不可辨或参考缺失，并在observation说明具体页/局部/行。错因未知不等于正误未知。'
REPORT = obj({'author': string(nonempty=True, limit=100), 'method': string(nonempty=True),
              'source_sha256': {**SHA,'description':'可省略，由后端按捕获原卷摘要填写；主动提供时必须完全一致。'}, 'expected_count': {'type': 'integer', 'minimum': 1, 'maximum': 100},
              'summary': string(nonempty=True), 'score_status': {'enum': ['unknown', 'estimated']},
              'priorities': array(obj({'label': string(nonempty=True), 'evidence': string(), 'action': string()})),
              'limitations': TEXTS, 'questions': array(QUESTION, minimum=1, maximum=100),
              'review': REVIEW},optional=('review','source_sha256'))
GOAL = obj({'id': ID, 'label': string(nonempty=True),
            'question_numbers': array({'type': 'integer', 'minimum': 1, 'maximum': 100}, minimum=1, unique=True),
            'topic_ids': IDS, 'stage': STAGE, 'evidence': string(nonempty=True),
            'priority': {'type': 'integer', 'minimum': 1, 'maximum': 5},
            'decision': {'enum': ['practice', 'monitor', 'no_candidate']}, 'reason': string(nonempty=True)})
EXERCISE = obj({'id': ID, 'goal_ids': array(ID, minimum=1, maximum=30, unique=True),
                'bank_id': ID, 'prompt': string(nonempty=True), 'expected': string(nonempty=True),
                'solution_note': string(nonempty=True), 'selection_reason': string(nonempty=True),
                'repeat_reason': {'anyOf': [{'type': 'null'}, string(nonempty=True)]}})
OBSERVATION = obj({'step': string(nonempty=True), 'stage': STAGE,
                   'status': {'enum': ['valid', 'error', 'unclear', 'consequence']}, 'evidence': string(nonempty=True)})
REF = obj({'kind': {'enum': ['question', 'attempt', 'report', 'result']}, 'id': ID})
FINDING = obj({'text': string(nonempty=True), 'evidence_refs': array(REF, minimum=1, maximum=30, unique=True)})

RESULTS = {
    'review_practice': obj({'summary':string(nonempty=True), 'revisions':array(obj({
        'probe_id':ID,'payload_revision':SHA,'status':{'enum':['corrected','unchanged','needs_material']},
        'expected':string(nonempty=True),'solution_note':string(nonempty=True),'reason':string(nonempty=True),
        'checks':array(obj({'claim':string(nonempty=True),'calculation':string(nonempty=True),'conclusion':string(nonempty=True)}),maximum=30),
        'limitations':TEXTS}),minimum=1,maximum=8)}),
    'analyze_paper': obj({'completion': {'enum': ['complete', 'partial', 'needs_material']}, 'report': REPORT}),
    'review_question': obj({'completion': {'enum': ['complete', 'partial', 'needs_material']},
                            'question': QUESTION, 'review': REVIEW, 'summary': string(nonempty=True),
                            'priorities': REPORT['properties']['priorities'],
                            'resolved_issue_indexes': array({'type': 'integer', 'minimum': 0}, unique=True),
                            'resolved_limitation_indexes': array({'type': 'integer', 'minimum': 0}, unique=True)}),
    'prepare_practice': obj({'goals': array(GOAL, maximum=100),
                             'exercises': array(EXERCISE, maximum=100), 'limitations': TEXTS}),
    'grade_attempt': obj({'attempt_id': ID, 'correct': {'type': ['boolean', 'null']},
                          'answer_status': {'enum': ['correct', 'wrong', 'unknown']},
                          'feedback': string(nonempty=True), 'reference_reasoning': string(),
                          'observations': array(OBSERVATION, maximum=100), 'first_error': ERROR,
                          'possible_causes': array(HYPOTHESIS, maximum=10), 'topic_ids': IDS,
                          'next_step': string(), 'needs_material': TEXTS}),
    'organize_knowledge': obj({'summary':string(nonempty=True), 'new_nodes':array(obj({'id':ID, 'parent_id':ID, 'name':string(nonempty=True,limit=80), 'aliases':TEXTS, 'reason':string(nonempty=True), 'source_ids':IDS}),maximum=50), 'mappings':array(obj({'source_id':ID,'source_revision':SHA,'topic_ids':IDS,'reason':string(nonempty=True),'event_topics':array(obj({'event_id':ID,'topic_ids':array(ID,maximum=1,unique=True)}),maximum=100)}),maximum=500), 'limitations':TEXTS}),
    'summarize_paper': obj({'source_refs': {**array(REF, minimum=1, maximum=300, unique=True),
                                          'description':'从learning_task.allowed_source_refs选取真实证据ID；所有发现的evidence_refs必须包含于此清单。'},
                            'overview': string(nonempty=True), 'key_findings': array(FINDING, maximum=30),
                            'improvements': {**array(FINDING, maximum=30),
                                             'description':'仅记录有前后证据支持的实际改善；没有改善证据时用空数组。待复核目标和复习建议放next_focus，不是已有改善。'}, 'unknowns': TEXTS,
                            'unfinished': TEXTS, 'next_focus': TEXTS}),
}


def default_version(kind):
    return '2.1' if kind=='review_practice' else '1.7' if kind in PREPARATION_KINDS else '1.8' if kind=='organize_knowledge' else VERSION


def result_schema(kind, version=None):
    import copy
    version=version or default_version(kind)
    if kind=='grade_attempt' and version=='1.11':
        schema=result_schema(kind,'1.0')
        schema['properties']['schema_version']={'const':'1.11'}
        schema['properties']['paper_id']={'type':'null'}
        schema['$id']='urn:mathlens:learning-result:1.11:grade_attempt'
        return schema
    if kind=='prepare_practice' and version=='1.10':
        shape=obj({'selections':array(obj({'bank_id':ID,'goal_ids':array(ID,minimum=1,maximum=30,unique=True),
            'selection_reason':string(nonempty=True),'prompt':string(nonempty=True)}),maximum=100),
            'limitations':{'type':'object','additionalProperties':string()}})
        return {'$schema':'https://json-schema.org/draft/2020-12/schema',
            'description':'面向学生的数学式使用$...$或$$...$$；只从对应候选选择，不自行搜索或生成题目。',
            **obj({'schema_version':{'const':version},'task_id':ID,'kind':{'const':kind},'paper_id':ID,
                   'input_revision':SHA,'author':string(nonempty=True,limit=100),'result':shape})}
    if kind not in KINDS:
        raise ValueError('未知学习任务类别')
    if kind in PREPARATION_KINDS:
        if version != '1.7':raise ValueError('通用知识准备任务须使用独立1.7契约')
        from app.knowledge.result_contracts import shape
        return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
                '$id': 'urn:mathlens:learning-result:' + version + ':' + kind,
                **obj({'schema_version': {'const': version}, 'task_id': ID, 'kind': {'const': kind},
                       'paper_id': {'type': 'null'}, 'input_revision': SHA, 'author': string(nonempty=True, limit=100),
                       'result': shape(kind)})}
    if version not in ('1.0','1.1','1.2','1.3','1.4','1.5','1.6','1.8','1.9','2.0','2.1') or kind == 'review_question' and version not in ('1.4','1.5','1.6','2.0'):
        raise ValueError('不支持的学习结果版本')
    if (version=='2.1') != (kind=='review_practice'):raise ValueError('2.1仅用于已布置练习的解答复核')
    if version=='2.0' and kind not in ('analyze_paper','review_question'):raise ValueError('2.0仅用于带固定通用参考的原卷分析/复核')
    if version=='1.8' and kind!='organize_knowledge':raise ValueError('1.8仅用于版本化知识映射')
    if version=='1.9' and kind not in ('prepare_practice','grade_attempt'):raise ValueError('1.9仅用于就绪选题及固定材料批改')
    if kind=='organize_knowledge' and version not in ('1.6','1.8'):raise ValueError('知识整理需要新任务契约')
    shape=copy.deepcopy(RESULTS[kind])
    if kind=='organize_knowledge' and version=='1.8':
        shape['properties']['new_nodes']['maxItems']=0
    if kind=='review_question':
        shape['properties']['question']['required'].extend(('answer_evidence','solution_guide','cause_summary'))
    if kind=='analyze_paper' and version in ('1.1','1.2','1.3','1.4','1.5','1.6','2.0'):
        report=shape['properties']['report']
        report['required'].append('review')
        report['properties']['questions']['items']['required'].append('answer_evidence')
        if version in ('1.2','1.3','1.4','1.5','1.6','2.0'):
            report['properties']['questions']['items']['required'].extend(('solution_guide','cause_summary'))
        if version in ('1.3','1.4','1.5','1.6','2.0'):
            report['properties']['questions']['items']['allOf'] = [{
                'if': {'properties': {'evidence_status': {'const': 'readable'}}},
                'then': {'properties': {
                    'knowledge': array(string(nonempty=True), minimum=1, maximum=100),
                    'fingerprint': {'properties': {
                        name: array(string(nonempty=True), minimum=1, maximum=100)
                        for name in ('methods','operations')}}}}}]
    if kind=='prepare_practice' and version in ('1.3','1.4','1.5','1.6','1.9'):
        shape['properties']['retained_exercises'] = array(obj({
            'probe_id': ID, 'goal_ids': array(ID, minimum=1, maximum=30, unique=True)}), maximum=500)
        shape['required'].append('retained_exercises')
    if kind=='prepare_practice' and version in ('1.5','1.6','1.9'):
        goal=shape['properties']['goals']['items']
        goal['properties']['related_probe_ids']=IDS
        goal['required'].append('related_probe_ids')
    if kind=='prepare_practice' and version=='1.9':
        exercise=shape['properties']['exercises']['items']
        exercise['properties']['annotation_id']=ID
        exercise['required'].append('annotation_id')
    if version=='2.0':
        shape['properties']['references']=array(obj({'number':{'type':'integer','minimum':1,'maximum':100},
            'bank_id':ID,'annotation_id':ID,'comparison':obj({name:string(nonempty=True) for name in ('conditions','target','options_and_figure')})}),maximum=100)
        shape['required'].append('references')
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': 'urn:mathlens:learning-result:' + version + ':' + kind,
            'description':'面向学生的数学式必须使用$...$行内或$$...$$独立公式分隔符。',
            **obj({'schema_version': {'const': version}, 'task_id': ID, 'kind': {'const': kind},
                   'paper_id': ID, 'input_revision': SHA, 'author': string(nonempty=True, limit=100),
                   'result': shape})}


def validate_result(payload, kind, version=None, *, analysis_context=None):
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError('结果必须为有限数值和合法JSON内容') from None
    if len(encoded.encode('utf8')) > 2 * 1024 * 1024:
        raise ValueError('学习结果超过2MiB')
    issues = sorted(Draft202012Validator(result_schema(kind,version or payload.get('schema_version'))).iter_errors(payload),
                    key=lambda e: '/'.join(map(str, e.absolute_path)))
    if issues:
        raise ValueError('结果结构不合法：' + '；'.join(
            '/'.join(map(str, e.absolute_path)) + ': ' + e.message[:240] for e in (issues if kind=='analyze_paper' else issues[:8])))
    result = payload['result']
    if kind == 'analyze_paper':
        errors=[]
        report = result['report']
        numbers = [q['number'] for q in report['questions']]
        if len(numbers) != report['expected_count'] or set(numbers) != set(range(1, report['expected_count'] + 1)):
            errors.append('报告必须逐一覆盖全部题号；缺失题号='+str(sorted(set(range(1,report['expected_count']+1))-set(numbers)))+'；未知或不可辨题也保留记录')
        if report['author'] != payload['author']:
            errors.append('结果作者与报告作者不一致')
        for q in report['questions']:
            if payload['schema_version'] in ('1.2','1.3','1.4','1.5','1.6','2.0'):
                if q['solution_guide'] is None and q['evidence_status']!='missing':
                    errors.append(f"第{q['number']}题："+'题干可读时每题须提供切入点、解题策略、关键步骤及注意事项')
                if q['correctness']!='correct' and not q['cause_summary'].strip():
                    errors.append(f"第{q['number']}题："+'错题、未完成及未知题须提供可能原因的分析或具体证据限制')
            if payload['schema_version'] in ('1.3','1.4','1.5','1.6','2.0') and q['evidence_status']=='readable':
                if any(not value.strip() for value in q['knowledge'] + q['fingerprint']['methods'] + q['fingerprint']['operations']):
                    errors.append(f"第{q['number']}题："+'题干可读时须提供具体考点、方法和必要操作，原因未知不影响考点分析')
            evidence=q.get('answer_evidence')
            if evidence:
                disputed=report.get('review',{}).get('status')=='needs_review' and bool(report['review']['issues'])
                if evidence['marking']!='none' and not evidence['marking_note'].strip():
                    errors.append(f"第{q['number']}题："+'存在批改时须描述其含义和位置，不能将批改答案当作原作答')
                if evidence['student_state']=='visible' and not evidence['student_work'].strip():
                    errors.append(f"第{q['number']}题："+'原作答可辨时须保留实际作答内容')
                if q['correctness']=='correct' and (evidence['student_state']=='not_attempted' or evidence['marking']=='wrong' and not disputed):
                    errors.append(f"第{q['number']}题："+'未作答或明确批错的题不能标正确；红笔更正不是原作答')
                if q['correctness']=='correct' and evidence['student_state']=='unreadable' and evidence['marking']!='correct':
                    errors.append(f"第{q['number']}题："+'没有可辨原作答或明确判对依据，不能标正确')
                if evidence['student_state']=='not_attempted' and q['first_error'] is not None:
                    errors.append(f"第{q['number']}题："+'未作答不能虚构首个计算或推导错误')
                if payload['schema_version'] in ('1.2','1.3','1.4','1.5','1.6','2.0') and evidence['student_state']=='not_attempted' and q['evidence_status']!='missing':
                    if q['correctness']!='wrong':
                        errors.append(f"第{q['number']}题："+'已确认未作答纳入错题补强，仍保留未作答状态')
                    if any(e['kind'] in ('exam_error','exam_success') for e in q['skill_events']):
                        errors.append(f"第{q['number']}题："+'空白只支持未完成证据，不证明某个数学操作确实做错')
                if evidence['marking']=='wrong' and q['correctness']=='unknown' and not disputed:
                    errors.append(f"第{q['number']}题："+'已明确批错不能因错因未知而将正误也记为未知')
                if (evidence['marking']=='correct' and q['correctness']=='wrong'
                    or evidence['student_state']=='unreadable' and q['correctness']=='unknown') and report.get('review',{}).get('status')=='verified':
                    errors.append(f"第{q['number']}题："+'批改冲突或原作答不可辨仍未核清，须暂缓选题')
            if q['correctness']!='correct' and any(e['kind']=='exam_success' for e in q['skill_events']):
                errors.append(f"第{q['number']}题："+'非正确题不能写入原卷成功证据')
            if not q['regions'] and not (q['evidence_status']=='missing' and q['correctness']=='unknown' and result['completion']!='complete'):
                errors.append(f"第{q['number']}题："+'仅缺失证据的未知题可无区域，且不得标整卷完整')
            if q['correctness'] == 'correct' and q['first_error'] is not None:
                errors.append(f"第{q['number']}题："+'有实质性步骤错误不能标记为完整正确；终值正误与过程分开')
            if q['correctness'] != 'unknown' and not q['reference_reasoning'].strip():
                errors.append(f"第{q['number']}题："+'判定作答前须提供核验解法与关键推导')
        if result['completion'] != 'complete' and not report['limitations']:
            errors.append('部分分析或需补材料须说明具体限制')
        review=report.get('review')
        if review and (review['status']=='needs_review' and not review['issues'] or review['status']=='verified' and review['issues']):
            errors.append('核对未完成须说明具体问题，核对通过不能保留未解决的冲突')
        if payload['schema_version'] in ('1.4','1.5','1.6','2.0') and review['status']=='verified' and result['completion']!='complete':
            errors.append('completion表示分析覆盖与核对是否完成，不表示学生是否全部答对或做完。核对通过时应为complete；已确认空白、错因未知或总分未核定不能使分析partial。若确有题意/判定/关键解法缺口，请保留needs_review并指出具体缺口。')
        if analysis_context:
            expected=analysis_context['expected_count']
            if expected and report['expected_count']!=expected:
                errors.append(f'expected_count须为后端提供的{expected}；缺失题号='+str(sorted(set(range(1,expected+1))-set(numbers))))
            references={e['number'] for e in analysis_context['entries'] if e['reference_available']}
            for q in report['questions']:
                evidence=q.get('answer_evidence',{})
                if q['number'] in references and evidence.get('student_state')=='visible' and q['evidence_status']=='readable' and q['correctness']=='unknown':
                    errors.append(f"第{q['number']}题：作答可辨且已提供参考答案/解析，须对照核验后判定正误；不能因错因未知而将正误记未知")
        if errors:raise ValueError('分析交付校验失败：\n'+'\n'.join(errors))
    elif kind == 'prepare_practice' and payload['schema_version']!='1.10':
        goals = {g['id']: g for g in result['goals']}
        if len(goals) != len(result['goals']):
            raise ValueError('补强目标标识重复')
        if len({e['id'] for e in result['exercises']}) != len(result['exercises']):
            raise ValueError('练习标识重复')
        if len({e['bank_id'] for e in result['exercises']}) != len(result['exercises']):
            raise ValueError('同一本地题只能布置一次，多目标应共享一个练习')
        counts = {g: 0 for g in goals}
        for exercise in result['exercises']:
            for goal in exercise['goal_ids']:
                if goal not in goals or goals[goal]['decision'] != 'practice':
                    raise ValueError('练习引用不存在或不需练习的目标')
                counts[goal] += 1
        if any(n > 2 for n in counts.values()):
            raise ValueError('每个重点目标最多两道代表题；重新合并或精简练习')
        retained = result.get('retained_exercises', [])
        if len({e['probe_id'] for e in retained}) != len(retained):
            raise ValueError('保留练习标识重复；追加不重复创建旧题')
        if any(g not in goals for e in retained for g in e['goal_ids']):
            raise ValueError('保留练习引用不存在的本轮目标')
    elif kind == 'grade_attempt':
        from app.learning.student_text import validate_student_text
        validate_student_text({k:result[k] for k in ('feedback','reference_reasoning','observations','first_error','possible_causes','next_step','needs_material') if k in result})
        if result['correct'] is True and result['first_error'] is not None:
            raise ValueError('存在实质性过程错误不能判为完全正确')
        if result['correct'] is not None and not result['reference_reasoning'].strip():
            raise ValueError('批改须给出核验解法，不能只匹配最终答案')
        if result['needs_material'] and result['correct'] is not None:
            raise ValueError('关键材料不足时保留正误未知')
    elif kind == 'summarize_paper':
        refs = {(r['kind'], r['id']) for r in result['source_refs']}
        if any((r['kind'], r['id']) not in refs for f in result['key_findings'] + result['improvements']
               for r in f['evidence_refs']):
            raise ValueError('总结结论必须引用本次来源清单中的证据')
    return payload
