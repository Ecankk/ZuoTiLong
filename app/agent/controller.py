"""Application operations on the single learning session."""
from app.agent.bridge import BridgeConflict
from app.errors import ServiceError
import threading,uuid

class AgentController:
    def __init__(self,runtime):
        self.runtime=runtime
        self.snapshot_lock=threading.Lock()
        self.snapshot_epoch=str(uuid.uuid4())
        self.snapshot_sequence=0
    def snapshot(self):
        # A public snapshot includes jobs stored outside the session projection.
        # Sequence complete observations, including reads with no session write.
        with self.snapshot_lock:
            bridge=self.runtime.bridge
            result=bridge.snapshot() if bridge else {'connected':False,'status':'disconnected','input_locked':False,'can_submit':False,'turns':[],'requests':[]}
            result.setdefault('revision',0)
            result['knowledge_preparation']=self.runtime.knowledge_catalog.preparation()['runs']
            self.snapshot_sequence+=1
            result.update(snapshot_epoch=self.snapshot_epoch,snapshot_sequence=self.snapshot_sequence)
            return result
    def invoke(self,action,body):
        bridge=self.runtime.bridge
        if not bridge:raise ValueError('学习助手尚未初始化')
        if action=='connect':return bridge.connect()
        if action=='task':
            extra={'task_scope':body['task_scope']} if body.get('task_scope') is not None else {}
            if body.get('kind')=='review_practice':extra['contract_version']='2.1'
            if body.get('kind') in ('analyze_paper','review_question','prepare_practice'):extra['practice_contract_version']='1.10'
            if body.get('kind') in ('analyze_paper','review_question'):
                with self.runtime.database.session() as conn:
                    previous=conn.execute('SELECT contract_version FROM workflow_jobs WHERE request_id=?',(body.get('request_id'),)).fetchone()
                extra['contract_version']=previous[0] if previous else '2.0'
            return bridge.queue_task(body.get('kind'),body.get('paper_id'),body.get('request_id'),body.get('attempt_id'),auto_prepare=body.get('kind') in ('analyze_paper','review_question'),review_request=body.get('review_request'),index_after=body.get('kind') in ('analyze_paper','review_question','prepare_practice','grade_attempt','review_practice'),**extra)
        if action in ('workflow-retry','workflow-cancel'):return bridge.workflow_action(body.get('job_id'),action.removeprefix('workflow-'))
        if action=='release':return bridge.release()
        if action=='send':return bridge.submit(body.get('text',''),body.get('request_id'),body.get('context'),body.get('image_ids',[]))
        if action=='respond':return bridge.respond(str(body.get('request_id')),body)
        if action=='retry':return bridge.retry()
        if action=='abandon':return bridge.abandon(body.get('confirmed'))
        if action=='upgrade-tools':return bridge.upgrade_tools(body.get('confirmed'))
        if action=='interrupt':return bridge.interrupt()
        raise ServiceError('not found',404)
    def summarize(self,paper_id,confirmed):
        if confirmed is not True:raise ValueError('重新总结会生成新的当前报告版本，需要二次确认')
        bridge=self.runtime.bridge
        if not bridge:raise ValueError('学习助手尚未初始化')
        with self.runtime.database.session() as conn:
            if not conn.execute('SELECT id FROM agent_reports WHERE paper_id=?',(paper_id,)).fetchone():raise ValueError('请先完成逐题分析，再聚合总结本卷')
        bridge.queue_task('summarize_paper',paper_id,str(uuid.uuid4()))
        return {'paper_id':paper_id,'agent_submitted':True}
