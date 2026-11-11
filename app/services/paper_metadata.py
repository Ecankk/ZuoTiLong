"""Explicit date corrections and duplicate-upload decisions, with receipts."""
from app.titles import paper_title
import json,uuid
from app.errors import ServiceError
from app.learning.tasks import digest,encode
from app.learning.loop import stamp
from app.learning.dates import normalize

def receipt(conn,body):
    key='paper-metadata-'+str(uuid.UUID(body['request_id']))
    old=conn.execute('SELECT payload FROM record_versions WHERE id=?',(key,)).fetchone()
    if old:
        old=json.loads(old[0])
        if old['request']!=body:raise ServiceError('request_id已用于不同操作',409)
        return key,dict(old['response'],reused=True)
    return key,None

def save(conn,key,kind,record_id,body,old,response):
    conn.execute('INSERT INTO record_versions VALUES(?,?,?,?,?,?)',(key,kind,record_id,encode(dict(request=body,old=old,response=response)),'用户确认试卷资料调整',stamp()))

def busy(conn,pid):
    return conn.execute("SELECT 1 FROM workflow_jobs WHERE paper_id=? AND status IN ('queued','dispatching','running')",(pid,)).fetchone() or conn.execute("SELECT 1 FROM learning_tasks WHERE paper_id=? AND status IN ('queued','running','repairing','result_saved')",(pid,)).fetchone()

def check(conn,paper):
    from app.bank.paper_candidates import location
    loc=location(paper);identity=dict(exam_year=int(loc['year']),math_type=loc['math_type']) if loc['status']=='located' and loc['math_type'] else None
    matches=[]
    if identity:
        for r in conn.execute("SELECT * FROM papers WHERE id!=? AND source_path IS NOT NULL AND source_path!='' AND import_decision!='withdrawn'",(paper['id'],)):
            other=location(dict(r))
            if other['status']=='located' and other['year']==str(identity['exam_year']) and other['math_type']==identity['math_type']:
                matches.append(dict(paper_id=r['id'],title=paper_title(r['title']),exam_date=r['exam_date'],exam_date_precision=r['exam_date_precision'],archived=bool(r['archived_at']),has_report=bool(conn.execute('SELECT 1 FROM agent_reports WHERE paper_id=?',(r['id'],)).fetchone())))
    result=dict(status='unresolved' if identity is None else 'same_exam_identity' if matches else 'clear',identity=identity,reason='请核对卷名中的年份和数一、数二或数三' if identity is None else None,matches=sorted(matches,key=lambda v:v['paper_id']))
    revision=digest(dict(id=paper['id'],sha=paper.get('source_sha256'),state=paper['import_decision'],matches=[v['paper_id'] for v in result['matches']]))
    return result,revision

def presentation(conn,paper):
    result,revision=check(conn,paper)
    return dict(duplicate_check=result,import_decision=paper['import_decision'],decision_revision=revision if paper['import_decision']!='accepted' else None)

class PaperMetadata:
    def __init__(self,config,database):self.config,self.database=config,database
    def dates(self,body):
        if body.get('confirmed') is not True:raise ValueError('请确认修改作答日期')
        ids=body['paper_ids']
        if not 1<=len(ids)<=50 or len(set(ids))!=len(ids):raise ValueError('请选择1–50张不同试卷')
        values=normalize(body.get('exam_date'),body.get('exam_date_precision'),body.get('exam_date_unknown_reason'))
        with self.database.session(write=True) as conn:
            key,prior=receipt(conn,body)
            if prior:return prior
            from app.knowledge.index import sources
            old_sources={s['source_id']:s for pid in ids for s in sources(conn,pid)};old=[]
            for pid in ids:
                row=conn.execute('SELECT * FROM papers WHERE id=?',(pid,)).fetchone()
                if not row:raise ServiceError('试卷不存在',404)
                if row['import_decision']=='withdrawn' or busy(conn,pid):raise ServiceError('请先结束试卷任务；已撤回的上传不能修改日期',409)
                old.append(dict(row));conn.execute('UPDATE papers SET exam_date=?,exam_date_precision=?,exam_date_unknown_reason=?,updated_at=? WHERE id=?',(*values.values(),stamp(),pid))
            from app.learning.semantic_dependencies import record
            for pid in ids:
                for s in sources(conn,pid):
                    before=old_sources.get(s['source_id'])
                    if not before or before['source_revision']==s['source_revision']:continue
                    def stable(v):return {**{k:x for k,x in v.items() if k not in ('source_revision','events')},'events':[{k:x for k,x in e.items() if k!='created_at'} for e in v['events']]}
                    if stable(before)!=stable(s):raise ServiceError('作答内容发生变化，不能只按日期沿用考点记录',409)
                    record(conn,'knowledge_semantic_adoption',s['source_id'],dict(source_id=s['source_id'],from_revision=before['source_revision'],to_revision=s['source_revision'],signature=None,events={e['id']:e['id'] for e in s['events']}))
            response=dict(updated=[dict(paper_id=pid,**values) for pid in ids],reused=False)
            save(conn,key,'paper_dates',','.join(ids),body,old,response);return response

    def decision(self,pid,body):
        if body.get('confirmed') is not True:raise ValueError('请确认本次上传的处理方式')
        with self.database.session(write=True) as conn:
            intent=dict(body,paper_id=pid);key,prior=receipt(conn,intent)
            if prior:return prior
            p=conn.execute('SELECT * FROM papers WHERE id=?',(pid,)).fetchone()
            if not p:raise ServiceError('试卷不存在',404)
            p=dict(p);_,revision=check(conn,p)
            if revision!=body['decision_revision'] or p['import_decision']=='accepted':raise ServiceError('上传状态已变化，请刷新后重试',409)
            if busy(conn,pid) or any(conn.execute('SELECT 1 FROM '+t+' WHERE paper_id=?',(pid,)).fetchone() for t in ('agent_reports','diagnostic_probes','learning_tasks','learning_results')):raise ServiceError('已有分析或练习记录，不能撤回这次上传',409)
            value='accepted' if body['decision']=='retake' else 'withdrawn'
            conn.execute('UPDATE papers SET import_decision=?,archived_at=?,updated_at=? WHERE id=?',(value,stamp() if value=='withdrawn' else None,stamp(),pid))
            response=dict(paper_id=pid,import_decision=value,reused=False);save(conn,key,'paper_import_decision',pid,intent,p,response);return response
