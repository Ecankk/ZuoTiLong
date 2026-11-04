"""Student submission and durable grading hand-off share one transaction."""
import hashlib,json,uuid
from app.learning.workflows import enqueue
from app.learning.loop import submit_probe,supplement_attempt
from app.services.papers import require_active_question
from app.storage.images import save_answer_image

def queue_attempt_grading(conn,attempt_id,root,data):
    """Persist the handoff in the same transaction as the student's submission."""
    attempt=conn.execute('''SELECT a.*,p.paper_id FROM probe_attempts a
      JOIN diagnostic_probes p ON p.id=a.probe_id WHERE a.id=?''',(attempt_id,)).fetchone()
    if not attempt:raise ValueError('作答不存在')
    version=hashlib.sha256(json.dumps({k:attempt[k] for k in
        ('response','images_json','image_roles_json','answer_exposed')},sort_keys=True).encode()).hexdigest()
    revision=conn.execute('SELECT count(*) FROM record_versions WHERE record_id=?',(attempt_id,)).fetchone()[0]
    request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'mathlens:grade:{attempt_id}:{version}:{revision}'))
    from app.learning.practice_knowledge import grading_version
    job=enqueue(conn,root,data,'grade_attempt',attempt['paper_id'],request_id,attempt_id,index_after=True,
                contract_version=grading_version(conn,attempt_id))
    return {'id':job['id'],'status':job['status']}

class PracticeService:
    def __init__(self,config,database):self.config,self.database=config,database
    def upload_images(self,contents):
        if not 1<=len(contents)<=4:raise ValueError('请上传 1–4 张照片')
        with self.database.session(write=True) as conn:
            return {'images':[save_answer_image(conn,self.config.data,content) for content in contents]}
    def submit(self,probe_id,body):
        with self.database.session(write=True) as conn:
            result=submit_probe(conn,probe_id,body)
            from app.learning.practice_knowledge import bind_attempt
            bind_attempt(conn,result['attempt_id'],reused=bool(result.get('reused')))
            result['job']=queue_attempt_grading(conn,result['attempt_id'],self.config.root,self.config.data)
            return result
    def supplement(self,attempt_id,body):
        with self.database.session(write=True) as conn:
            result=supplement_attempt(conn,attempt_id,body)
            result['job']=queue_attempt_grading(conn,attempt_id,self.config.root,self.config.data)
            return result
    def feedback(self,probe_id,attempt_id):
        with self.database.session(write=True) as conn:
            return self.queue_feedback(conn,probe_id,attempt_id)
    def queue_feedback(self,conn,probe_id,attempt_id):
        row=conn.execute('SELECT p.question_id FROM probe_attempts a JOIN diagnostic_probes p ON p.id=a.probe_id WHERE a.id=? AND p.id=?',(attempt_id,probe_id)).fetchone()
        if not row:raise ValueError('作答与检验题不一致')
        require_active_question(conn,row['question_id'])
        return {'job':queue_attempt_grading(conn,attempt_id,self.config.root,self.config.data),'attempt_id':attempt_id}
    def review_question(self,question_id,body):
        with self.database.session(write=True) as conn:
            row=conn.execute('SELECT paper_id FROM questions WHERE id=?',(question_id,)).fetchone()
            if not row:raise ValueError('原题不存在')
            job=enqueue(conn,self.config.root,self.config.data,'review_question',row['paper_id'],body.get('request_id'),auto_prepare=True,index_after=True,practice_contract_version='1.10',contract_version='2.0',
                review_request={**{k:body.get(k) for k in ('report_id',)},'question_id':question_id,'note':body.get('note',''),'image_ids':body.get('image_ids',[]),'image_roles':body.get('image_roles',{})})
            return {'agent_queued':True,'job_id':job['id']}
