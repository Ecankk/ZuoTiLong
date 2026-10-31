"""Read-only projections of a paper's effective practice plan and its history."""
from __future__ import annotations

import json


def practice_state(conn, paper_id):
    report = conn.execute('SELECT id FROM agent_reports WHERE paper_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',
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
    result['explicit_membership'] = payload['schema_version'] in ('1.3','1.4','1.5','1.6','1.9')
    if payload['schema_version']=='1.9':
        result['deferred_probes']=([dict(r) for r in conn.execute('SELECT probe_id,reason FROM practice_deferred_probes WHERE result_id=? ORDER BY probe_id',(plan['id'],))]
                                  if conn.execute("SELECT 1 FROM sqlite_master WHERE name='practice_deferred_probes'").fetchone() else [])
    result['last_added_count'] = len(payload['result']['exercises'])
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
