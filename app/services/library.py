"""Local library browsing and explicit reveal preferences."""
import json,uuid
from app.common import now_iso
from app.bank.access import public_bank,reveal,preferences,save_preferences,save_agent_prompt,init_access

class LibraryService:
    def __init__(self,config,database):self.config,self.database=config,database
    def browse(self,category='',year=''):
        with self.database.session() as conn:
            bank=[public_bank(conn,r[0],view='library') for r in conn.execute("SELECT id FROM bank_questions WHERE source!='本地示例题库' ORDER BY id")]
            from app.bank.entities import visible_ids
            source_ids=[r[0] for r in conn.execute("SELECT id FROM bank_questions ORDER BY id")]
            bank=[public_bank(conn,bid,view='library') for bid in visible_ids(conn,source_ids)]
            bank.sort(key=lambda b:(-int(b['year']) if str(b['year']).isdecimal() else 0,b['math_type'],b['number'],b['id']))
            return {'bank':[b for b in bank if (not category or str(category) in {str(v) for v in b['math_types']}) and (not year or b['year']==year)]}
    def search(self,**query):
        from app.bank.retrieval import recall
        with self.database.session() as conn:
            return recall(conn,self.config.data,internal=False,**query)
    def reveal(self,bank_id,role,confirmed):
        with self.database.session(write=True) as conn:return reveal(conn,bank_id,role,confirmed)
    def preferences(self):
        with self.database.session() as conn:return preferences(conn)
    def save_preferences(self,body):
        with self.database.session(write=True) as conn:return save_preferences(conn,body)
    def save_prompt(self,body):
        with self.database.session(write=True) as conn:return save_agent_prompt(conn,body)
    def correct_navigation(self,bank_id,body):
        from app.bank.metadata import correct_navigation
        with self.database.session(write=True,library_write=True) as conn:
            return correct_navigation(conn,self.config.data,bank_id,body)
    def preview_identity(self,body):
        from app.bank.identity_reviews import preview
        with self.database.session() as conn:
            return preview(conn,self.config.data,**body)
    def review_identity(self,body):
        from app.bank.identity_reviews import apply
        with self.database.session(write=True,library_write=True) as conn:
            return apply(conn,self.config.data,body)
    def import_text(self,body):
        incoming=body if isinstance(body,list) else body.get('questions',[])
        if not isinstance(incoming,list) or any(not isinstance(q,dict) for q in incoming):raise ValueError('题库内容须为题目数组')
        with self.database.session(write=True,library_write=True) as conn:
            for item in incoming:
                qid=item.get('id') or 'bank-'+uuid.uuid4().hex[:10]
                stem=item.get('stem') or item.get('content') or item.get('question') or ''
                tags=item.get('tags') or item.get('keywords') or ([item['chapter']] if item.get('chapter') else [])
                # Do not delete an identity that may already be referenced by a
                # saved attempt. New source/version ingestion has its own gate.
                old=conn.execute('SELECT id FROM bank_questions WHERE id=?',(qid,)).fetchone()
                if old:raise ValueError('题目ID已存在，请使用保留版本和历史引用的题源导入流程')
                conn.execute('INSERT INTO bank_questions(id,source,source_ref,stem,answer,explanation,tags_json,fingerprint_json,difficulty,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (qid,item.get('source') or '本地题库',item.get('source_ref') or item.get('uid') or item.get('id'),stem,item.get('answer') or item.get('solution'),item.get('explanation') or item.get('analysis'),json.dumps(tags,ensure_ascii=False),json.dumps(item.get('fingerprint',{}),ensure_ascii=False),int(item.get('difficulty') or 3),now_iso()))
            conn.commit();init_access(conn)
            return {'imported':len(incoming)}
