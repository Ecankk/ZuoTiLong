"""Read-only projections of a paper's effective practice plan and its history."""
from __future__ import annotations

import json


def practice_state(conn, paper_id):
    from app.bank.capture_view import active
    view=active(conn)
    if view is None:return _practice_state(conn,paper_id)
    if paper_id not in view.plan_cache:view.plan_cache[paper_id]=_practice_state(conn,paper_id)
    return view.plan_cache[paper_id]

def _practice_state(conn,paper_id):
    report = conn.execute('SELECT id,report_json FROM agent_reports WHERE paper_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',
                          (paper_id,)).fetchone()
    plan = conn.execute('''SELECT r.id,r.payload_json,t.input_json FROM learning_results r
      JOIN learning_tasks t ON t.id=r.task_id WHERE r.paper_id=? AND r.kind='prepare_practice'
      ORDER BY r.created_at DESC,r.rowid DESC LIMIT 1''', (paper_id,)).fetchone()
    result = {'paper_id': paper_id, 'report_id': report['id'] if report else None,
              'result_id': plan['id'] if plan else None, 'is_current': False,
              'explicit_membership': False, 'probe_ids': [], 'last_added_count': 0, 'last_retained_count': 0}
    if not plan:
        return result
    result['is_current'] = bool(report and any(r['id'] == report['id']
        for r in json.loads(plan['input_json']).get('reports', [])))
    payload = json.loads(plan['payload_json'])
    result['explicit_membership'] = payload['schema_version'] in ('1.3','1.4','1.5','1.6','1.9','1.10')
    if payload['schema_version'] in ('1.9','1.10'):
        result['deferred_probes']=([dict(r) for r in conn.execute('SELECT probe_id,reason FROM practice_deferred_probes WHERE result_id=? ORDER BY probe_id',(plan['id'],))]
                                  if conn.execute("SELECT 1 FROM sqlite_master WHERE name='practice_deferred_probes'").fetchone() else [])
    result['last_added_count'] = len(payload['result'].get('exercises',payload['result'].get('selections',[])))
    if result['explicit_membership']:
        result['probe_ids'] = [r[0] for r in conn.execute('''SELECT m.probe_id FROM practice_plan_members m
          JOIN diagnostic_probes p ON p.id=m.probe_id WHERE m.result_id=? AND p.paper_id=?
          AND p.id NOT IN (SELECT probe_id FROM retired_probes) ORDER BY p.created_at,p.id''',
          (plan['id'], paper_id))]
    else:
        # Legacy plans implicitly left every non-retired exercise in the paper.
        # Preserve that interpretation until an explicit plan is delivered.
        result['probe_ids'] = [r[0] for r in conn.execute('''SELECT id FROM diagnostic_probes WHERE paper_id=?
          AND id NOT IN (SELECT probe_id FROM retired_probes) ORDER BY created_at,id''', (paper_id,))]
    if report and not result['is_current']:
        saved=json.loads(plan['input_json']);baseline={r['id'] for r in saved.get('reports',[])}
        current=json.loads(report['report_json']);cursor=current
        # Only explicit scoped-review ancestry may adopt an earlier plan.
        seen=set();parent=None
        while cursor.get('revision',{}).get('kind')=='review_question':
            parent=cursor['revision']['parent_report_id']
            if parent in baseline:break
            if parent in seen:break
            seen.add(parent)
            row=conn.execute('SELECT report_json FROM agent_reports WHERE id=? AND paper_id=?',(parent,paper_id)).fetchone()
            if not row:break
            cursor=json.loads(row[0])
        if parent in baseline:
            from app.learning.semantic_dependencies import reports_changed
            changed=reports_changed(saved,current,parent);result['affected_numbers']=sorted(changed)
            result['is_current']=True
            retained=[]
            for pid in result['probe_ids']:
                groups={}
                for r in conn.execute('''SELECT g.id,q.number FROM probe_goals pg
                    JOIN goal_questions gq ON gq.goal_id=pg.goal_id JOIN questions q ON q.id=gq.question_id
                    JOIN practice_goals g ON g.id=pg.goal_id WHERE pg.probe_id=? AND g.result_id=?''',(pid,plan['id'])):
                    groups.setdefault(r[0],set()).add(str(r[1]))
                if not groups:
                    groups[pid]={str(r[0]) for r in conn.execute('SELECT q.number FROM diagnostic_probes p JOIN questions q ON q.id=p.question_id WHERE p.id=?',(pid,))}
                if any(not dependencies.intersection(changed) for dependencies in groups.values()):retained.append(pid)
            result['probe_ids']=retained
    result['last_retained_count'] = max(0, len(result['probe_ids']) - result['last_added_count'])
    return result


def plan_goals(conn, state):
    if not state['result_id']:
        return []
    if state['explicit_membership']:
        return [dict(r) for r in conn.execute('SELECT * FROM practice_goals WHERE result_id=? ORDER BY rowid',
                                             (state['result_id'],))]
    # Include the goals of retained legacy exercises, even when the last legacy
    # result only contained monitoring goals and an empty exercises array.
    return [dict(r) for r in conn.execute('''SELECT DISTINCT g.* FROM practice_goals g
      WHERE g.paper_id=? AND (g.result_id=? OR EXISTS (
        SELECT 1 FROM probe_goals pg JOIN diagnostic_probes p ON p.id=pg.probe_id
        WHERE pg.goal_id=g.id AND p.paper_id=g.paper_id
        AND p.id NOT IN (SELECT probe_id FROM retired_probes))) ORDER BY g.rowid''',
      (state['paper_id'], state['result_id']))]
