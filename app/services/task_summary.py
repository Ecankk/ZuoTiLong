"""Small task projection; never copy chat messages, tool outputs or write tickets."""
from app.common import rows
from app.agent.errors import BridgeConflict
from app.errors import ServiceError
from app.services.frontend_reads import page

TASK_STATUSES = ('queued', 'running', 'completed', 'blocked', 'failed', 'cancelled')
LABELS = {'analyze_paper':'分析', 'review_question':'复核', 'prepare_practice':'选择练习', 'grade_attempt':'批改练习',
          'organize_knowledge':'整理考点', 'summarize_paper':'总结', 'review_practice':'复核练习',
          'maintain_catalog':'整理通用考点', 'annotate_questions':'整理题库'}


class TaskSummary:
    def __init__(self, runtime):self.rt = runtime

    def _state(self):
        bridge = self.rt.bridge
        if bridge is None:
            return {}, {}, dict(status='unavailable', reason='disabled', message='学习服务未启用')
        with bridge.lock:
            state = getattr(bridge, 'state', {})
            active = next((t for t in state.get('turns', []) if t['request_id'] == state.get('active_request')), {})
            small = {k: state.get(k) for k in ('status', 'active_request', 'external_control')}
            small.update(connected=getattr(bridge, 'connected', False), connecting=getattr(bridge, 'connecting', False),preparing=getattr(bridge,'preparing',False))
            active = {k: active.get(k) for k in ('task_id', 'status')}
            availability = bridge.availability() if hasattr(bridge, 'availability') else dict(status='checking', reason=None, message='正在准备学习服务')
        return small, active, availability

    def _records(self):
        with self.rt.database.session() as conn:
            jobs = rows(conn, '''SELECT j.id,j.kind,j.paper_id,j.attempt_id,j.status,j.task_id,j.error,
                j.recovery_required,j.created_at,j.updated_at,p.title paper_title,t.status task_status FROM workflow_jobs j
                LEFT JOIN papers p ON p.id=j.paper_id LEFT JOIN learning_tasks t ON t.id=j.task_id''')
            from app.learning.workflows import can_cancel
            for job in jobs:job['can_cancel']=can_cancel(conn,job)
            # Older direct tasks have no workflow row but still own a remote turn.
            direct = rows(conn, '''SELECT t.id,t.kind,t.paper_id,t.attempt_id,t.status,t.error,t.created_at,t.updated_at,
                p.title paper_title FROM learning_tasks t LEFT JOIN papers p ON p.id=t.paper_id
                WHERE NOT EXISTS(SELECT 1 FROM workflow_jobs j WHERE j.task_id=t.id)''')
        for task in direct:
            task.update(task_id=task['id'], task_status=task['status'], recovery_required=0, direct=True)
        return jobs+direct

    def read(self, status=None, offset=0, limit=20):
        if status is not None and status not in TASK_STATUSES:raise ValueError('任务状态不合法')
        state, active_turn, availability = self._state()
        locked = bool(state.get('active_request') or state.get('connecting') or state.get('external_control') or state.get('preparing'))
        items = []; active_id = None
        for job in self._records():
            raw = job['status']
            value = ('running' if raw in ('running', 'dispatching', 'result_saved', 'repairing') else
                     'cancelled' if raw == 'abandoned' else 'failed' if raw in ('failed', 'interrupted') else raw)
            if value not in TASK_STATUSES:value = 'blocked'
            owned = job['task_id'] and job['task_id'] == active_turn.get('task_id')
            if owned:
                active_id = job['id']
                if state.get('status') in ('failed', 'interrupted'):value = 'failed'
            actions = []
            if not locked and self.rt.bridge is not None and not job.get('direct'):
                if job['recovery_required'] or value in ('blocked', 'failed'):
                    actions.append('retry')
                if job.get('can_cancel'):actions.append('cancel')
            elif owned and state.get('connected') and state.get('status') in ('failed', 'interrupted') and not state.get('external_control'):
                actions.append('retry')
            label = LABELS.get(job['kind'], '处理学习任务')
            title = '《'+job['paper_title']+'》' if job['paper_title'] else ''
            message = ('正在'+label+title if value == 'running' else '等待'+label+title if value == 'queued' else
                       label+title+('已完成' if value == 'completed' else '已取消' if value == 'cancelled' else '需要处理'))
            if job['task_status'] == 'result_saved' and value == 'running':message = label+title+'结果已保存，正在核对完成状态'
            items.append(dict(id=job['id'], kind=job['kind'], paper_id=job['paper_id'], paper_title=job['paper_title'],
                              attempt_id=job['attempt_id'], status=value, progress={'message': message}, error=job['error'],
                              created_at=job['created_at'], updated_at=job['updated_at'], allowed_actions=actions))
        rank = {'running':0, 'queued':1, 'blocked':2, 'failed':2, 'completed':3, 'cancelled':3}
        items.sort(key=lambda j: (j['created_at'], j['id']), reverse=True)
        items.sort(key=lambda j: rank[j['status']])
        active = next((i for i in items if i['id'] == active_id), None) or next((i for i in items if i['status'] == 'running'), None)
        failed = sum(i['status'] in ('failed', 'blocked') for i in items)
        global_status = ('agent_unavailable' if availability['status'] == 'unavailable' else 'connecting' if state.get('connecting') else
                         'attention_required' if state.get('external_control') or failed else 'running' if active else 'idle')
        return dict(page([i for i in items if status is None or i['status'] == status], offset, limit),
                    status=global_status, availability=availability, active=active,
                    queued_count=sum(i['status'] == 'queued' for i in items), failed_count=failed)

    def action(self, job_id, action):
        if action not in ('retry', 'cancel'):raise ValueError('任务操作不合法')
        # Read eligibility under the bridge fence. Network reconciliation below
        # must release it so the transport's event reader can finish callbacks.
        bridge = self.rt.bridge
        if bridge is None:
            if not any(j['id']==job_id for j in self._records()):raise ServiceError('任务不存在',404)
            raise BridgeConflict('学习服务未启用')
        with bridge.lock:
            target = None; pos = 0
            while True:
                listing = self.read(offset=pos, limit=100)
                target = next((i for i in listing['items'] if i['id'] == job_id), None)
                if target or listing['next_offset'] is None:break
                pos = listing['next_offset']
            if target is None:raise ServiceError('任务不存在', 404)
            if action not in target['allowed_actions']:raise BridgeConflict('当前任务状态不允许此操作')
            state, active, _ = self._state()
            expected = active.get('task_id') if action == 'retry' and state.get('active_request') else None
        if expected is not None:
            bridge.retry(expected_task_id=expected)
        else:
            bridge.workflow_action(job_id, action)
        self.rt.wake()
        return self.read()
