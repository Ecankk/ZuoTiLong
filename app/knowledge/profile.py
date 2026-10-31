"""Conservative, read-only state aggregation of indexed evidence."""


def aggregate(item):
    # Several legacy labels in one question can describe the same failure.
    # Keep observations, count that answer only once for this concept.
    grouped = {}
    priority={'exam_error':3,'probe_failure':3,'exam_success':2,'probe_success':2}
    for event in item['events']:
        key=('exam',event['question_id']) if event['source']=='exam' else ('attempt',event['id'])
        old=grouped.get(key)
        if old is None or priority.get(event['kind'],0)>priority.get(old['kind'],0):
            grouped[key]=event
    events=sorted(grouped.values(),key=lambda e:(e['created_at'],e['id']))
    item['events']=events
    item['question_ids']=sorted(set(item['question_ids']))
    item['probe_ids']=sorted(set(item['probe_ids']))
    effective=[e for e in events if e['kind'] in priority and (e['source']!='exam' or e.get('verified'))]
    failures=[e for e in effective if e['kind'] in ('exam_error','probe_failure')]
    successes=[e for e in effective if e['kind'] in ('exam_success','probe_success')]
    item.update(failures=len(failures),successes=len(successes),
        pending=sum(e not in effective and not e['kind'].startswith('assisted') for e in events),
        independent_probe_successes=sum(e['kind']=='probe_success' for e in effective),
        assisted_successes=sum(e['kind']=='assisted_success' for e in events),
        attempt_count=len({e['attempt_id'] for e in events if e.get('attempt_id')}),
        papers=len({s['paper_id'] for s in item['scopes']}))
    if not effective:
        item.update(state='证据不足' if item['scopes'] else '未覆盖',state_reason='已关联题目不等于掌握；暂无足够的有效表现证据。')
    elif effective[-1]['kind'] in ('exam_error','probe_failure'):
        item.update(state='需要关注',state_reason='最近有效作答仍有相关错误；仅反映有证据的知识环节。')
    else:
        last_error=max((i for i,e in enumerate(effective) if e['kind'] in ('exam_error','probe_failure')),default=-1)
        following=effective[last_error+1:]
        diverse=len({e['paper_id'] for e in following})>=2 or len({e['created_at'][:10] for e in following})>=2
        kind = item.get('origin', {}).get('node_kind')
        narrow = kind == 'atom' if kind is not None else item.get('scope_level') == 'concept'
        initial=narrow and len(following)>=2 and diverse
        reason='已有跨卷或间隔成功证据，仅适用于已记录的知识环节。' if initial else (
            '已有有效成功，仅覆盖该知识范围已记录的部分内容，不能据此判断整个范围掌握。' if not narrow else
            '已有有效成功，继续用后续试卷观察；一次答对不代表整个考点掌握。')
        item.update(state='初步掌握' if initial else '巩固中',state_reason=reason)
