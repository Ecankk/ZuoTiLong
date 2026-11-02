"""Durable application stage scheduling, separate from Codex transport."""
import json,uuid
from contextlib import closing
from app.agent.errors import BridgeConflict, SessionControlConflict

class WorkflowCoordinator:
    def __init__(self,bridge):self.bridge=bridge

    def _workflow_listing(self):
        if not self.bridge.learning_db.is_file() or not (self.bridge.data/'workspace.json').is_file():
            return []
        from app.learning.workflows import listing
        with closing(self.bridge._learning_connection()) as conn:
            return listing(conn)

    def _workflow_loop(self):
        while not self.bridge.closing:
            self.bridge.workflow_wakeup.wait(0.5)
            self.bridge.workflow_wakeup.clear()
            if self.bridge.closing:
                return
            try:
                self.bridge.ensure_connection()
                self.bridge._drain_workflows()
            except Exception as exc:
                # Keep the durable job for recovery. Do not start a second
                # worker or silently replace the learning session on failure.
                with self.bridge.lock:
                    self.bridge.state['workflow_error'] = '阶段调度暂未完成，材料已保留：' + str(exc)[:300]

    def queue_task(self, kind, paper_id, request_id, attempt_id=None, *, auto_prepare=False, review_request=None, index_after=False, task_scope=None, knowledge_request=None, contract_version=None,practice_contract_version=None):
        from app.learning.workflows import enqueue,request_practice
        with self.bridge.lock:
            self.bridge.assert_user_write_allowed()
            with closing(self.bridge._learning_connection()) as conn, conn:
                if kind=='prepare_practice' and practice_contract_version=='1.9':
                    if (attempt_id is not None or auto_prepare or review_request is not None or task_scope is not None
                            or knowledge_request is not None or contract_version not in (None,'1.9')):
                        raise ValueError('选题请求不能夹带其他任务范围或旧契约')
                    request_practice(conn,self.bridge.root,self.bridge.data,paper_id,request_id,index_after=index_after)
                else:
                    enqueue(conn, self.bridge.root, self.bridge.data, kind, paper_id, request_id,
                            attempt_id, auto_prepare=auto_prepare, review_request=review_request, index_after=index_after,task_scope=task_scope,knowledge_request=knowledge_request,contract_version=contract_version,practice_contract_version=practice_contract_version)
            self.bridge.workflow_wakeup.set()
            return self.bridge.snapshot()

    def workflow_action(self, job_id, action):
        from app.learning.workflows import cancel_job, retry_job
        with self.bridge.lock:
            if self.bridge.state['active_request'] or self.bridge.connecting or self.bridge.state.get('external_control'):
                raise BridgeConflict('请先完成或核对当前会话，再处理等待中的阶段')
            with closing(self.bridge._learning_connection()) as conn, conn:
                if action == 'retry':
                    job=conn.execute('SELECT * FROM workflow_jobs WHERE id=?',(job_id,)).fetchone()
                    if job and job['recovery_required']:
                        from app.learning.workflows import enqueue,mark
                        mark(conn,job['id'],'abandoned','恢复后显式继续，旧执行记录保留')
                        replacement=enqueue(conn,self.bridge.root,self.bridge.data,job['kind'],job['paper_id'],str(uuid.uuid4()),
                                job['attempt_id'],workflow_id=job['workflow_id'],auto_prepare=bool(job['auto_prepare']),
                                review_request=json.loads(job['review_json']) if job['review_json'] else None,index_after=bool(job['index_after']),
                                task_scope=json.loads(job['scope_json']) if job['scope_json'] else None,
                                knowledge_request=json.loads(job['knowledge_json']) if job['knowledge_json'] else None,
                                contract_version=job['contract_version'],index_contract_version=job['index_contract_version'],
                                practice_contract_version=job['practice_contract_version'],continue_practice=bool(job['continue_practice']))
                        conn.execute("UPDATE knowledge_preparation_items SET job_id=? WHERE job_id=? AND status='running'",(replacement['id'],job['id']))
                    elif job and job['task_id']:
                        from app.learning.tasks import task_record
                        task=task_record(conn,job['task_id'])
                        if not self.bridge.connected or task['session_id']!=self.bridge.state['session_id']:
                            raise BridgeConflict('请先连接原学习会话，再核对并重试原任务')
                        if task['status']=='completed' and (job['auto_prepare'] or job['index_after'] or job['continue_practice'] or task['kind'] in ('maintain_catalog','annotate_questions')):
                            from app.learning.workflows import continue_job,mark
                            continue_job(conn,self.bridge.root,self.bridge.data,dict(job),task)
                            mark(conn,job['id'],'completed')
                        else:
                            self.bridge._recover_workflow_turn(conn,task)
                            self.bridge.state['status']='failed'
                            self.bridge._save()
                    else:
                        retry_job(conn, self.bridge.root, self.bridge.data, job_id)
                elif action == 'cancel':
                    cancel_job(conn, job_id)
                else:
                    raise ValueError('阶段操作无效')
            if action=='retry' and self.bridge.state['active_request']:
                return self.bridge.retry()
            self.bridge.workflow_wakeup.set()
            return self.bridge.snapshot()

    def _drain_workflows(self):
        from app.learning.workflows import guard, mark, next_job, reconcile
        with self.bridge.lock:
            if (self.bridge.closing or not self.bridge.connected or self.bridge.connecting or self.bridge.state['active_request']
                    or self.bridge.state.get('external_control') or self.bridge.state['status'] != 'idle'):
                return
            if not self.bridge._workflow_listing():
                return
            with closing(self.bridge._learning_connection()) as conn, conn:
                reconcile(conn, self.bridge.root, self.bridge.data)
                orphan = conn.execute('''SELECT t.* FROM workflow_jobs j JOIN learning_tasks t
                  ON t.id=j.task_id WHERE j.status='running' ORDER BY j.created_at,j.rowid LIMIT 1''').fetchone()
                if orphan:
                    if orphan['session_id'] != self.bridge.state['session_id']:
                        self.bridge.state['workflow_error'] = '待续任务属于原学习会话，请核对会话身份；未另建任务。'
                        return
                    if not orphan['turn_id'] and orphan['status'] == 'queued':
                        # The task commit preceded saving the bridge turn. No
                        # remote send occurs before that bridge save.
                        conn.execute("UPDATE workflow_jobs SET status='queued' WHERE task_id=?", (orphan['id'],))
                    else:
                        self.bridge._recover_workflow_turn(conn, dict(orphan))
                        self.bridge._save()
                else:
                    orphan = None
            if orphan and orphan['turn_id']:
                # A saved task is not evidence that its remote turn stopped.
                # Reconcile that exact turn before retrying or continuing.
                try:
                    self.bridge._reconcile(self.bridge.transport)
                except SessionControlConflict as exc:
                    self.bridge._block_control(str(exc))
                return
            with closing(self.bridge._learning_connection()) as conn, conn:
                job = next_job(conn)
                if not job:
                    return
                job = dict(job)
                try:
                    if guard(conn, self.bridge.root, self.bridge.data, job['kind'], job['paper_id'], job['attempt_id'],
                             review_request=json.loads(job['review_json']) if job['review_json'] else None,
                             task_scope=json.loads(job['scope_json']) if job['scope_json'] else None,
                             knowledge_request=json.loads(job['knowledge_json']) if job['knowledge_json'] else None) != json.loads(job['guard_json']):
                        raise ValueError('等待期间原卷分析或作答版本已改变；请核对后按当前材料重试本阶段')
                except ValueError as exc:
                    mark(conn, job['id'], 'blocked', exc)
                    return
                mark(conn, job['id'], 'dispatching')
            self.bridge.draining_workflows = True
            try:
                extra={'contract_version':job['contract_version']}
                if job['scope_json']:extra['task_scope']=json.loads(job['scope_json'])
                if job['knowledge_json']:extra['knowledge_request']=json.loads(job['knowledge_json'])
                self.bridge.submit_task(job['kind'], job['paper_id'], job['request_id'], job['attempt_id'],
                                 workflow_id=job['workflow_id'],
                                 review_request=json.loads(job['review_json']) if job['review_json'] else None,**extra)
                with closing(self.bridge._learning_connection()) as conn, conn:
                    task = conn.execute('SELECT id FROM learning_tasks WHERE request_id=?', (job['request_id'],)).fetchone()
                    mark(conn, job['id'], 'running', task_id=task['id'])
                self.bridge.state.pop('workflow_error', None)
            except Exception as exc:
                with closing(self.bridge._learning_connection()) as conn, conn:
                    task = conn.execute('SELECT id FROM learning_tasks WHERE request_id=?', (job['request_id'],)).fetchone()
                    mark(conn, job['id'], 'blocked', exc, task['id'] if task else None)
            finally:
                self.bridge.draining_workflows = False

    def _recover_workflow_turn(self, conn, task):
        from app.learning.tasks import rekey_task
        task['run_token'] = rekey_task(conn, task['id'], task['run_token'])
        text = ('恢复先前的' + task['kind'] + '任务。只完成当前阶段，先用context读取本任务schema和输入版本，'
                '用read_skill读取当前阶段规范，核对实际材料并按任务契约交付；已有保存回执不重复写入。')
        turn = next((t for t in self.bridge.state['turns'] if t['request_id'] == task['request_id']), None)
        if turn is None:
            context={'paper_id':task['paper_id']} if task['paper_id'] is not None else {}
            inputs=(self.bridge.context.preparation_inputs(text,task['request_id'])
                    if task['kind'] in ('maintain_catalog','annotate_questions')
                    else self.bridge._inputs(text,context,task['request_id']))
            turn = {'request_id': task['request_id'], 'text': text, 'context': context,
                    'inputs': inputs,
                    'messages': [], 'created_at': task['created_at'], 'retired_turn_ids': [], 'image_ids': [],
                    'dispatch_nonce': uuid.uuid4().hex, 'repair_attempts': 0}
            self.bridge.state['turns'].append(turn)
        turn.update(task_id=task['id'], task_kind=task['kind'], run_token=task['run_token'],
                    workflow_id=task['workflow_id'], attempt_id=task['attempt_id'],
                    codex_turn_id=task['turn_id'], status='running')
        self.bridge.state.update(active_request=task['request_id'], status='running', error=None,
                          activity='正在核对原任务的实际执行状态')
