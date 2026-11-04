"""Serial, disposable Codex executions. Durable state belongs to local tasks."""
from contextlib import closing
import copy,hashlib,json,tempfile,threading,time,uuid
from pathlib import Path
from app.agent.transport import CodexProcess
from app.agent.errors import BridgeConflict,AgentUnavailable
from app.agent.session_store import SessionStore
from app.agent.models import catalog,selected
from app.learning.loop import stamp
from app.version import VERSION

DEFAULT_MODEL='gpt-6-luna'
DEFAULT_EFFORT='xhigh'
FORMULAS='所有面向学生的数学式必须用$...$行内或$$...$$独立公式包裹，包括反馈、下一步建议、分析说明及选题理由。'

class CodexBridge:
    def __init__(self,root:Path,data:Path,transport_factory=CodexProcess):
        self.root,self.data=root.resolve(),data.resolve();self.data.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.operations=threading.RLock()
        self.transport_factory=transport_factory;self.transport=None
        self.connected=False;self.connecting=False;self.closing=False;self.auto_connect=False
        self.finishing=False;self.generation=0;self.unavailable_reason=None;self.next_connect_check=0
        self.connect_thread=None;self.dispatch_thread=None;self.finishing_thread=None;self.model_catalog=[];self.prompts={}
        from app.storage.boundaries import workspace_config
        self.learning_db=workspace_config(self.data,self.root).database
        self.db=self.data/'agent-session.db';self.session_store=SessionStore(self.db)
        self.state=self.session_store.load()
        self.state.update(status='disconnected',active_request=None,session_id=None,error=None,requests=[],external_control=False,activity='等待学习任务')
        self.workflow_wakeup=threading.Event();self.draining_workflows=False
        self._recover();self._save()
        self.workflow_thread=threading.Thread(target=self._workflow_loop,daemon=True);self.workflow_thread.start()

    def _learning_connection(self):
        from app.storage.boundaries import workspace_config,connect_workspace
        return connect_workspace(workspace_config(self.data,self.root))

    def _runtime_directory(self):
        directory=self.data/'agent-runtime'
        if directory.is_relative_to(self.root):
            # Development fixtures and legacy installs can keep data in the
            # checkout. Their execution directory must still escape AGENTS.md.
            key=hashlib.sha256(str(self.data).encode()).hexdigest()[:20]
            directory=Path(tempfile.gettempdir())/'mathlens-agent-runtime'/key
        directory.mkdir(parents=True,exist_ok=True)
        from app.agent.methods import ROLE_SKILLS
        template=Path(__file__).with_name('runtime_agents.md').read_text(encoding='utf-8')
        text=template.replace('{{ROLE_SKILLS}}','\n'.join('- '+kind+' → '+', '.join('mathlens-'+n for n in names) for kind,names in ROLE_SKILLS.items()))
        document=directory/'AGENTS.md'
        if not document.is_file() or document.read_text(encoding='utf-8')!=text:document.write_text(text,encoding='utf-8')
        return directory.resolve()

    def _recover(self):
        if not self.learning_db.is_file():return
        from app.learning.tasks import receipt,finish_task
        from app.learning.workflows import reconcile
        with closing(self._learning_connection()) as conn,conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='learning_tasks'").fetchone():return
            for task in conn.execute("SELECT * FROM learning_tasks WHERE status IN ('queued','running','result_saved','repairing')").fetchall():
                if receipt(conn,task['id']):
                    if task['kind']=='annotate_questions':
                        from app.storage.boundaries import enable_library_writes,workspace_config
                        enable_library_writes(conn,workspace_config(self.data,self.root))
                    finish_task(conn,task['id'])
                else:
                    conn.execute("UPDATE learning_tasks SET status='failed',run_token=?,error=?,updated_at=? WHERE id=?",
                        (uuid.uuid4().hex,'执行已中断；重试将在新会话重新执行',stamp(),task['id']))
            reconcile(conn,self.root,self.data)
        for turn in self.state['turns']:
            if turn.get('status') in ('queued','running','repairing','result_saved'):
                with closing(self._learning_connection()) as conn:
                    saved=receipt(conn,turn['task_id']) if turn.get('task_id') else None
                turn.update(status='completed' if saved else 'failed',receipt=saved)

    def _save(self):self.session_store.save(self.state)
    def _active(self):return next((t for t in self.state['turns'] if t['request_id']==self.state['active_request']),None)
    def _workflow_listing(self):
        if not self.learning_db.is_file():return []
        from app.learning.workflows import listing
        with closing(self._learning_connection()) as conn:return listing(conn)

    def snapshot(self):
        with self.lock:
            value=copy.deepcopy(self.state)
            value.update(connected=self.connected,workflows=self._workflow_listing(),can_submit=False,
                         input_locked=bool(self.state['active_request'] or self.connecting or self.finishing))
            value['turns']=value['turns'][-30:]
            for t in value['turns']:
                for key in ('inputs','run_token','dispatch_nonce'):t.pop(key,None)
                t['messages']=[]
            return value

    def assert_user_write_allowed(self):
        if self.state['active_request'] or self.connecting or self.finishing:raise BridgeConflict('请等待当前任务交付或停止后重试')

    def connect(self):
        with self.lock:
            if self.connected or self.connecting or self.finishing:return self.snapshot()
            self.connecting=True;self.closing=False
            self.connect_thread=threading.Thread(target=self._connect,daemon=True);self.connect_thread.start()
            return self.snapshot()

    def _connect(self):
        with self.operations:
            with self.lock:
                if self.connected or self.closing or self.finishing:return
                self.connecting=True;self.generation+=1;generation=self.generation
                previous=self.transport;self.transport=None
            if previous:previous.close()
            transport=None
            try:
                transport=self.transport_factory(self._runtime_directory(),self.data,lambda m:self.event(m,generation),lambda r:self.disconnected(r,generation))
                with self.lock:
                    if self.closing or generation!=self.generation:
                        transport.close();return
                    self.transport=transport
                transport.request('initialize',{'clientInfo':{'name':'mathlens','title':'MathLens','version':VERSION},'capabilities':{'experimentalApi':True}})
                transport.send({'method':'initialized','params':{}})
                account=transport.request('account/read',{'refreshToken':False})
                if not account.get('account'):raise AgentUnavailable('not_logged_in','学习服务尚未登录，请先登录。')
                items=catalog(transport)
                with self.lock:
                    if self.closing or generation!=self.generation:
                        transport.close();return
                    self.transport=transport;self.model_catalog=items;self.connected=True
                    self.unavailable_reason=None;self.state.update(status='idle',error=None,activity='学习服务可用')
            except Exception as exc:
                if transport:transport.close()
                with self.lock:
                    self.unavailable_reason=getattr(exc,'reason','other');self.connected=False
                    self.state.update(status='disconnected',error=str(exc))
            finally:
                with self.lock:
                    self.connecting=False
                    if not self.closing:self._save()
                    self.workflow_wakeup.set()

    def models(self):
        if not self.connected:self._connect()
        return {**self.availability(),'items':copy.deepcopy(self.model_catalog) if self.connected else []}

    def availability(self):
        reason=self.unavailable_reason
        if not self.connected and self.transport_factory is CodexProcess:
            from app.agent.transport import codex_executable
            if codex_executable() is None:reason='not_installed'
        return dict(status='available' if self.connected else 'checking' if self.connecting or not reason else 'unavailable',reason=reason,
                    message={'not_installed':'未安装学习服务，请先安装。','not_logged_in':'学习服务尚未登录，请先登录。','other':'学习服务暂不可用，请检查本机服务。'}.get(reason,'学习服务可用' if self.connected else '有任务时自动连接'))

    def ensure_connection(self):
        if self.auto_connect and not self.closing and not self.connected and not self.connecting and not self.finishing and time.monotonic()>=self.next_connect_check:
            if any(j['status']=='queued' and not j['recovery_required'] for j in self._workflow_listing()):
                self.next_connect_check=time.monotonic()+2;self.connect()

    def _workflow_loop(self):
        while not self.closing:
            self.workflow_wakeup.wait(.5);self.workflow_wakeup.clear()
            if self.closing:return
            try:self.ensure_connection();self._drain_workflows()
            except Exception as exc:
                with self.lock:self.state['workflow_error']=str(exc)

    def queue_task(self,kind,paper_id,request_id,attempt_id=None,**kwargs):
        from app.learning.workflows import enqueue,request_practice
        with self.lock:
            self.assert_user_write_allowed()
            with closing(self._learning_connection()) as conn,conn:
                if kind=='prepare_practice':
                    if attempt_id or kwargs.get('review_request') or kwargs.get('task_scope') or kwargs.get('knowledge_request') or kwargs.get('auto_prepare'):
                        raise ValueError('选题请求不能夹带其他任务范围')
                    request_practice(conn,self.root,self.data,paper_id,request_id,index_after=kwargs.get('index_after',False))
                else:enqueue(conn,self.root,self.data,kind,paper_id,request_id,attempt_id,**kwargs)
            self.workflow_wakeup.set();return self.snapshot()

    def _drain_workflows(self):
        from app.learning.workflows import reconcile,next_job,guard,mark
        with self.lock:
            if self.closing or not self.connected or self.finishing or self.state['active_request']:return
            with closing(self._learning_connection()) as conn,conn:
                reconcile(conn,self.root,self.data);row=next_job(conn)
                if not row:return
                job=dict(row)
                extra={k:json.loads(job[c]) if job[c] else None for k,c in (('review_request','review_json'),('task_scope','scope_json'),('knowledge_request','knowledge_json'))}
                try:
                    if guard(conn,self.root,self.data,job['kind'],job['paper_id'],job['attempt_id'],**extra)!=json.loads(job['guard_json']):raise ValueError('任务材料已变化，请重试此阶段')
                    mark(conn,job['id'],'dispatching')
                except ValueError as exc:mark(conn,job['id'],'blocked',exc);return
            try:
                self.submit_task(job['kind'],job['paper_id'],job['request_id'],job['attempt_id'],workflow_id=job['workflow_id'],contract_version=job['contract_version'],**extra)
            except Exception as exc:
                with closing(self._learning_connection()) as conn,conn:mark(conn,job['id'],'failed',exc)

    def submit_task(self,kind,paper_id,request_id,attempt_id=None,**kwargs):
        from app.learning.tasks import create_task
        from app.agent.material_package import initial_inputs
        with self.lock:
            self.assert_user_write_allowed()
            if not self.connected:raise BridgeConflict('学习服务尚未连接')
            with closing(self._learning_connection()) as conn:
                old=conn.execute('SELECT * FROM learning_tasks WHERE request_id=?',(request_id,)).fetchone()
                if old:
                    if (old['kind'],old['paper_id'],old['attempt_id'])!=(kind,paper_id,attempt_id):raise ValueError('同一请求不能更换任务')
                    return self.snapshot()
                from app.bank.access import preferences
                setting=selected(kind,preferences(conn),self.model_catalog)
            sid='pending-session-'+uuid.uuid4().hex
            with closing(self._learning_connection()) as conn,conn:
                task=create_task(conn,self.root,self.data,kind,paper_id,sid,request_id,attempt_id=attempt_id,**kwargs)
                conn.execute("UPDATE workflow_jobs SET task_id=?,status='running' WHERE request_id=?",(task['id'],request_id))
            turn=dict(request_id=request_id,task_id=task['id'],task_kind=kind,run_token=task['run_token'],session_id=sid,codex_turn_id=None,
                      status='running',context={'paper_id':paper_id} if paper_id is not None else {},attempt_id=attempt_id,messages=[],model_settings=setting,created_at=stamp())
            self.state['turns'].append(turn);self.state.update(session_id=sid,active_request=request_id,status='running',model_settings=setting)
            self._save()
            try:
                # A stable local nonce permits initial receipts before turn/start returns.
                nonce='pending-'+uuid.uuid4().hex
                with closing(self._learning_connection()) as conn,conn:
                    conn.execute("UPDATE learning_tasks SET turn_id=?,status='running' WHERE id=?",(nonce,task['id']))
                    turn['codex_turn_id']=nonce
                    inputs=initial_inputs(conn,self.root,self.data,task['id'],self._task_lease(turn))
                turn['inputs']=inputs;self._save()
                self.dispatch_thread=threading.Thread(target=self._dispatch,args=(turn,),daemon=True);self.dispatch_thread.start()
            except Exception as exc:self._stop(turn,str(exc));raise
            return self.snapshot()

    def _task_lease(self,turn):return dict(task_id=turn['task_id'],session_id=turn['session_id'],run_token=turn['run_token'],turn_id=turn['codex_turn_id'])
    def _bind(self,turn,tid):
        if turn['codex_turn_id'].startswith('pending-'):
            with closing(self._learning_connection()) as conn,conn:
                conn.execute('UPDATE learning_tasks SET turn_id=? WHERE id=? AND turn_id=?',(tid,turn['task_id'],turn['codex_turn_id']))
            turn['codex_turn_id']=tid

    def _dispatch(self,turn):
        try:
            transport=self.transport;setting=turn['model_settings']
            from app.agent.tools import SCHEMA,DESCRIPTION
            cwd=str(self._runtime_directory())
            response=transport.request('thread/start',{'cwd':cwd,'sandbox':'read-only','approvalPolicy':'never','model':setting['model'],
                'config':{'model_reasoning_effort':setting['effort'],'skills.include_instructions':False,
                    'skills.bundled.enabled':False,'features.plugins':False,'features.apps':False},'ephemeral':False,
                'dynamicTools':[{'type':'function','name':'mathlens','description':DESCRIPTION,'inputSchema':SCHEMA}]})
            actual=response.get('model',response.get('thread',{}).get('model'))
            if actual and actual!=setting['model']:raise ValueError('Codex未采用所选模型，任务停止；请检查设置')
            effort=response.get('reasoningEffort',response.get('thread',{}).get('reasoningEffort'))
            if effort and effort!=setting['effort']:raise ValueError('Codex未采用所选推理强度，任务停止；请检查设置')
            with self.lock:
                if self._active() is not turn:return
                sid=response['thread']['id']
                with closing(self._learning_connection()) as conn,conn:
                    conn.execute('UPDATE learning_tasks SET session_id=? WHERE id=?',(sid,turn['task_id']))
                turn['session_id']=sid;self.state['session_id']=sid;self._save()
            response=transport.request('turn/start',{'threadId':turn['session_id'],'input':turn['inputs'],'cwd':cwd,
                'sandboxPolicy':{'type':'readOnly'},'approvalPolicy':'never','model':setting['model'],'effort':setting['effort']})
            with self.lock:
                if self._active() is turn:self._bind(turn,response['turn']['id']);self._save()
        except Exception as exc:
            with self.lock:
                if self._active() is turn:self._stop(turn,str(exc))

    def _stop(self,turn,error=None):
        from app.learning.tasks import receipt
        with closing(self._learning_connection()) as conn,conn:
            saved=receipt(conn,turn['task_id'])
            if not saved:conn.execute("UPDATE learning_tasks SET status='failed',run_token=?,error=?,updated_at=? WHERE id=?",(uuid.uuid4().hex,error or '执行结束但未交付有效结果',stamp(),turn['task_id']))
            from app.learning.workflows import reconcile
            reconcile(conn,self.root,self.data)
        turn.update(status='completed' if saved else 'failed',receipt=saved,error=None if saved else error,finished_at=stamp())
        self.state.update(active_request=None,session_id=None,status='idle',error=None if saved else error)
        self.finishing=True;self._save()
        old=self.transport;self.transport=None;self.connected=False;self.generation+=1
        def close_execution():
            if old:old.close()
            with self.lock:self.finishing=False;self._save();self.workflow_wakeup.set()
        self.finishing_thread=threading.Thread(target=close_execution,daemon=True);self.finishing_thread.start()

    def event(self,message,generation=None):
        with self.lock:
            if generation is not None and generation!=self.generation:return
            params=message.get('params',{});turn=self._active()
            if not turn or params.get('threadId')!=turn['session_id']:return
            tid=params.get('turnId') or params.get('turn',{}).get('id')
            if tid:self._bind(turn,tid)
            if tid and tid!=turn['codex_turn_id']:return
            method=message.get('method')
            if method=='item/tool/call' and 'id' in message:
                try:
                    if params.get('tool')!='mathlens':raise ValueError('只允许mathlens学习工具')
                    from app.agent.tools import execute
                    args=params.get('arguments',{});args=json.loads(args) if isinstance(args,str) else args
                    content=execute(self.root,self.data,args['action'],args.get('payload',{}),lease=self._task_lease(turn))
                    result={'success':True,'contentItems':[{'type':'inputText','text':v['text']} if v['type']=='text' else {'type':'inputImage','imageUrl':f"data:{v['mimeType']};base64,{v['data']}"} for v in content]}
                except Exception as exc:result={'success':False,'contentItems':[{'type':'inputText','text':str(exc)}]}
                self.transport.send({'id':message['id'],'result':result})
                from app.learning.tasks import receipt
                with closing(self._learning_connection()) as conn:saved=receipt(conn,turn['task_id'])
                if saved:self._stop(turn)
            elif method=='turn/completed':self._stop(turn,(params.get('turn',{}).get('error') or {}).get('message'))
            elif method=='model/rerouted':self._stop(turn,'服务变更了所选模型；任务停止，请检查可用模型设置')
            elif 'id' in message:self.transport.send({'id':message['id'],'error':{'code':-32601,'message':'请用本任务材料直接判断并交付，不请求外部交互'}})
            self._save()

    def disconnected(self,reason,generation=None):
        with self.lock:
            if generation is not None and generation!=self.generation:return
            self.connected=False;self.connecting=False
            turn=self._active()
            if turn:self._stop(turn,reason)
            else:self.state.update(status='disconnected',error=reason);self._save()

    def workflow_action(self,job_id,action):
        from app.learning.workflows import retry_job,cancel_job
        with self.lock:
            self.assert_user_write_allowed()
            with closing(self._learning_connection()) as conn,conn:
                if action=='retry':retry_job(conn,self.root,self.data,job_id)
                elif action=='cancel':cancel_job(conn,job_id)
                else:raise ValueError('任务操作不合法')
            self.workflow_wakeup.set();return self.snapshot()

    def retry(self,**kwargs):
        failed=next((j for j in self._workflow_listing() if j['status'] in ('failed','blocked','interrupted')),None)
        if not failed:raise BridgeConflict('没有待重试任务')
        return self.workflow_action(failed['id'],'retry')
    def interrupt(self):
        with self.lock:
            turn=self._active()
            if turn:self._stop(turn,'用户停止了任务，可在新会话重试')
            return self.snapshot()
    def submit(self,*args,**kwargs):raise BridgeConflict('仅支持结构化任务，不支持学习聊天')
    def release(self):return self.interrupt()
    def abandon(self,confirmed):
        if confirmed is not True:raise ValueError('请确认停止任务')
        return self.interrupt()
    def upgrade_tools(self,confirmed):raise BridgeConflict('任务自动使用当前工具，无需升级固定会话')
    def respond(self,*args):raise BridgeConflict('任务不支持追问交互')
    def close(self):
        with self.lock:
            self.closing=True;self.workflow_wakeup.set()
            if self._active():self._stop(self._active(),'应用退出，重试将使用新会话')
            transport=self.transport;self.transport=None;self.connected=False;self.generation+=1
        if transport:transport.close()
        for worker in (self.connect_thread,self.dispatch_thread,self.workflow_thread,self.finishing_thread):
            if worker and worker is not threading.current_thread():worker.join(timeout=5)
