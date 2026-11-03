"""Paper lifecycle and source preparation, independent of HTTP."""
from app.storage.paths import paper_path, relative_file, resolve_file, connection_data
import hashlib,json,math,sqlite3,uuid
from datetime import date
from pathlib import Path
from app.common import now_iso,as_json,json_load,rows
from app.documents.pdf import extract_pdf,match_bank_questions
from app.documents.progress import write_progress
from app.learning.workflows import enqueue

def set_paper_archive(conn: sqlite3.Connection, paper_id: str, archived: bool, confirmed: bool) -> dict:
    """Archive or restore a paper without deleting evidence.

    The HTTP layer requires an explicit confirmation flag. Archive is the
    default lifecycle action; reports, answers and learning events remain
    addressable so a later restore can recover the same paper workspace.
    """
    if confirmed is not True:
        raise ValueError("需要二次确认后才能改变试卷归档状态")
    row = conn.execute("SELECT id, archived_at FROM papers WHERE id=?", (paper_id,)).fetchone()
    if not row:
        raise ValueError("试卷不存在")
    if bool(row['archived_at']) == archived:
        return {"paper_id": paper_id, "archived": archived, "reused": True}
    stamp = now_iso()
    conn.execute('INSERT INTO record_versions VALUES(?,?,?,?,?,?)',
                 ('version-'+uuid.uuid4().hex,'paper_archive',paper_id,json.dumps(dict(row)),
                  '用户确认归档' if archived else '用户确认恢复',stamp))
    conn.execute("UPDATE papers SET archived_at=?, updated_at=? WHERE id=?", (stamp if archived else None, stamp, paper_id))
    return {"paper_id": paper_id, "archived": archived, "updated_at": stamp}

def require_active_question(conn,question_id):
    row=conn.execute('SELECT p.archived_at FROM questions q JOIN papers p ON p.id=q.paper_id WHERE q.id=?',(question_id,)).fetchone()
    if not row:raise ValueError('题目不存在')
    if row[0]:raise ValueError('请先恢复已归档试卷')

def confirm_paper_score(conn, paper_id, body):
    paper=conn.execute('SELECT * FROM papers WHERE id=?',(paper_id,)).fetchone()
    if not paper:raise ValueError('试卷不存在')
    if paper['archived_at']:raise ValueError('请先恢复已归档试卷')
    if body.get('confirmed') is not True:raise ValueError('请确认本卷核定分数')
    score,total,category=body.get('score'),body.get('total_score',150),body.get('math_type')
    if type(score) not in (int,float) or type(total) not in (int,float) or not math.isfinite(score) or not math.isfinite(total) or not 0<total<=1000 or not 0<=score<=total:
        raise ValueError('分数必须为有效数字且在满分范围内')
    if type(category) is not int or category not in (1,2,3):raise ValueError('请选择本卷数学类别')
    created=now_iso()
    conn.execute('INSERT INTO record_versions VALUES(?,?,?,?,?,?)',
                 ('version-'+uuid.uuid4().hex,'paper_score',paper_id,json.dumps(dict(paper)),
                  '用户核定总分',created))
    conn.execute('UPDATE papers SET score=?,total_score=?,math_type=?,score_confirmed_at=?,updated_at=? WHERE id=?',
                 (score,total,category,created,created,paper_id))
    return {'paper_id':paper_id,'score':score,'total_score':total,'score_confirmed_at':created}

class PaperService:
    def __init__(self,config,database):self.config,self.database=config,database

    def _match_questions(self,conn,paper,questions):
        from app.bank.paper_candidates import location
        from app.bank.exam_identity import candidates
        bank_rows=rows(conn,'SELECT * FROM bank_questions')
        for item in bank_rows:
            item['tags']=json_load(item.pop('tags_json',None),[])
            item['fingerprint']=json_load(item.pop('fingerprint_json',None),{})
        by_id={item['id']:item for item in bank_rows}
        source=location(dict(paper))
        for question in questions:
            pool=bank_rows
            # An explicit exam locator restricts the text comparison. It does
            # not itself confirm mathematical identity or raise the score.
            if source['status']=='located' and source['math_type'] is not None:
                number=str(question['number'])
                ids=candidates(conn,source['year'],source['math_type'],int(number)) if number.isascii() and number.isdecimal() else []
                pool=[by_id[bid] for bid in ids if bid in by_id]
            match_bank_questions([question],pool)
        return questions

    def _rematch_saved(self,conn,paper):
        questions=rows(conn,'SELECT * FROM questions WHERE paper_id=? ORDER BY created_at,id',(paper['id'],))
        for question in self._match_questions(conn,paper,questions):
            conn.execute('UPDATE questions SET match_bank_id=?,match_score=? WHERE id=?',
                         (question['match_bank_id'],question['match_score'],question['id']))
        return questions

    def analyze(self,conn: sqlite3.Connection,paper_id: str) -> dict:
        paper = as_json(conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone())
        if not paper:
            raise ValueError("试卷不存在")
        if paper.get('archived_at'):raise ValueError('请先恢复已归档试卷')
        source_path = paper.get("source_path")
        if not source_path:
            raise ValueError("这张试卷没有本地 PDF 文件")
        pdf_path = paper_path(self.config.data, source_path, self.config.root)
        if self.config.papers not in pdf_path.parents or not pdf_path.is_file():
            raise ValueError("试卷文件不在本地资料目录中")
        correction=conn.execute("SELECT payload FROM record_versions WHERE record_id=? AND kind='question_segmentation' ORDER BY rowid DESC LIMIT 1",(paper_id,)).fetchone()
        if correction:
            saved=json.loads(correction[0])
            if hashlib.sha256(pdf_path.read_bytes()).hexdigest()!=saved['source_sha256']:
                raise ValueError('原PDF已变化，不能继续使用已纠正切分')
            current=self._rematch_saved(conn,paper)
            return dict(paper=paper,questions=current,engine=paper['analysis_engine'],message='保留已确认的人工切分',
                        warnings=[],created_questions=len(current),agent_task=None)

        write_progress(self.config.data,paper_id,status='running',phase='opening',pages_done=0,pages_total=None,
                       questions=0,warnings=[],message='正在读取原PDF')
        try:
            result = extract_pdf(pdf_path,cache_root=self.config.data/'ocr-cache',
                                 on_progress=lambda **fields:write_progress(self.config.data,paper_id,**fields))
        except Exception as exc:
            write_progress(self.config.data,paper_id,status='failed',message=str(exc))
            raise
        extracted = self._match_questions(conn,paper,result["questions"])
        existing = rows(conn, "SELECT * FROM questions WHERE paper_id=? ORDER BY created_at", (paper_id,))
        created = now_iso()
        for index, item in enumerate(extracted):
            old = next((row for row in existing if str(row.get("number")) == str(item["number"])), None)
            if old is None and index < len(existing) and "待补充题干" in (existing[index].get("stem") or ""):
                old = existing[index]
            qid = old["id"] if old else f"{paper_id}-q-{index + 1:02d}"
            values = (
                item["number"],
                item["stem"],
                json.dumps(item.get("fingerprint") or {}, ensure_ascii=False),
                item.get("knowledge") or (old.get("knowledge") if old else None),
                item.get("page_start"),
                item.get("page_end"),
                json.dumps(item.get("bbox"), ensure_ascii=False) if item.get("bbox") else None,
                item.get("ocr_confidence", 0),
                item.get("match_bank_id"),
                item.get("match_score", 0),
                item["stem"],
            )
            if old and old["id"] == qid:
                if conn.execute("SELECT question_id FROM question_diagnoses WHERE question_id=?", (qid,)).fetchone():
                    continue  # Re-extraction must not overwrite an Agent-reviewed attempt.
                conn.execute(
                    """UPDATE questions SET number=?, stem=?, fingerprint_json=?, knowledge=?, page_start=?, page_end=?,
                       bbox_json=?, ocr_confidence=?, match_bank_id=?, match_score=?, source_text=? WHERE id=?""",
                    values + (qid,),
                )
            else:
                conn.execute(
                    """INSERT INTO questions(id,paper_id,number,subject,stem,score_earned,max_score,correctness,review_status,
                       knowledge,fingerprint_json,page_start,page_end,bbox_json,ocr_confidence,match_bank_id,match_score,source_text,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (qid, paper_id, item["number"], "数学一", item["stem"], 0, 0, "unknown", "待诊断",
                     item.get("knowledge"), values[2], item.get("page_start"), item.get("page_end"), values[6],
                     item.get("ocr_confidence", 0), item.get("match_bank_id"), item.get("match_score", 0), item["stem"], created),
                )
            conn.execute("UPDATE questions SET regions_json=? WHERE id=?", (json.dumps(item.get("regions", []), ensure_ascii=False), qid))
        has_report = conn.execute("SELECT id FROM agent_reports WHERE paper_id=?", (paper_id,)).fetchone()
        status = "diagnosed" if has_report else "segmented" if result.get("complete") else "needs_review"
        conn.execute(
            "UPDATE papers SET import_status=?, page_count=?, analysis_engine=?, analysis_message=?, analyzed_at=?, updated_at=? WHERE id=?",
            (status, len(result["pages"]), result["engine"], result["message"], created, created, paper_id),
        )
        conn.commit()
        task_dir = self.config.data / "tasks" / paper_id
        task_dir.mkdir(parents=True, exist_ok=True)
        page_images = []
        import pymupdf as fitz
        with fitz.open(str(pdf_path)) as document:
            for idx, page in enumerate(document):
                target = task_dir / f"page-{idx+1:02d}.png"
                if not target.is_file():
                    page.get_pixmap(matrix=fitz.Matrix(1.8,1.8), alpha=False).save(str(target))
                page_images.append(str(target))
        request = {"paper_id":paper_id,"source_sha256":result["source_sha256"],"source_pdf":str(pdf_path),
                   "page_images":page_images,"questions":extracted,"status":"report_available" if has_report else "awaiting_agent",
                   "instructions":"Read original pages and work, verify OCR against images. Use the current context.learning_task result schema and scoped result delivery. Do not invent probe results, scores or causes. See docs/agent-workflow.md."}
        task_file = task_dir / "request.json"
        task_file.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding="utf-8")
        write_progress(self.config.data,paper_id,status='complete' if result.get('complete') else 'needs_review',
                       phase='ready',message=result['message'])
        return {
            "paper": as_json(conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()),
            "questions": rows(conn, "SELECT * FROM questions WHERE paper_id=? ORDER BY number", (paper_id,)),
            "engine": result["engine"],
            "message": result["message"],
            "warnings": result["warnings"],
            "created_questions": len(extracted),
            "agent_task": str(task_file),
        }

    def import_pdf(self,filename,content,fields,*,queue_agent=True):
        import pymupdf
        if not filename or not content or len(content)>80*1024*1024:
            raise ValueError('PDF 上传大小须为 1 字节至 80 MB')
        try:
            with pymupdf.open(stream=content,filetype='pdf') as document:
                if document.is_encrypted or not len(document):raise ValueError('unreadable')
        except Exception:raise ValueError('请上传可读取、未加密的 PDF') from None
        digest=hashlib.sha256(content).hexdigest()
        with self.database.session() as conn:
            previous=as_json(conn.execute('SELECT * FROM papers WHERE source_sha256=? ORDER BY created_at LIMIT 1',(digest,)).fetchone())
        if previous:return {'paper':previous,'sha256':digest,'reused':True},200
        paper_id='paper-'+uuid.uuid4().hex[:10]
        filename=Path(filename).name
        folder=self.config.papers/paper_id;folder.mkdir(parents=True,exist_ok=True)
        target=folder/filename;target.write_bytes(content)
        source=relative_file(self.config.data,target)
        created=now_iso()
        with self.database.session(write=True) as conn:
            conn.execute('INSERT INTO papers(id,title,exam_date,source_name,source_path,source_sha256,import_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (paper_id,fields.get('title') or Path(filename).stem,fields.get('exam_date') or date.today().isoformat(),filename,source,digest,'needs_review',created,created))
            paper=as_json(conn.execute('SELECT * FROM papers WHERE id=?',(paper_id,)).fetchone())
        result={'paper':paper,'sha256':digest}
        try:
            with self.database.session(write=True) as conn:
                analysis=self.analyze(conn,paper_id)
                result.update(paper=analysis['paper'],created_questions=analysis['created_questions'],warnings=analysis['warnings'])
                if queue_agent:
                    job=enqueue(conn,self.config.root,self.config.data,'analyze_paper',paper_id,
                        str(uuid.uuid5(uuid.NAMESPACE_URL,'mathlens:paper:'+digest)),auto_prepare=True,index_after=True,practice_contract_version='1.9',contract_version='2.0')
                    result.update(agent_queued=True,job_id=job['id'])
                else:result['agent_queued']=False
        except (ValueError,RuntimeError,ImportError) as exc:result['analysis_warning']=str(exc)
        return result,201

    def analyze_and_queue(self,paper_id,confirmed=False):
        with self.database.session(write=True) as conn:
            if conn.execute('SELECT 1 FROM agent_reports WHERE paper_id=?',(paper_id,)).fetchone() and confirmed is not True:
                raise ValueError('重新分析将生成当前版本，需要二次确认；旧报告及真实作答保留')
            result=self.analyze(conn,paper_id)
            job=enqueue(conn,self.config.root,self.config.data,'analyze_paper',paper_id,str(uuid.uuid4()),auto_prepare=True,index_after=True,practice_contract_version='1.9',contract_version='2.0')
            return {**result,'agent_queued':True,'job_id':job['id']}

    def archive(self,paper_id,archived,confirmed):
        with self.database.session(write=True) as conn:return set_paper_archive(conn,paper_id,archived,confirmed)
    def score(self,paper_id,body):
        with self.database.session(write=True) as conn:return confirm_paper_score(conn,paper_id,body)
    def create(self,body):
        paper_id='paper-'+uuid.uuid4().hex[:10];created=now_iso()
        with self.database.session(write=True) as conn:
            conn.execute('INSERT INTO papers(id,title,exam_date,score,total_score,duration,source_name,import_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (paper_id,body.get('title') or '未命名试卷',body.get('exam_date'),float(body.get('score') or 0),float(body.get('total_score') or 150),int(body.get('duration') or 0),body.get('source_name'),'needs_review',created,created))
            return {'paper':as_json(conn.execute('SELECT * FROM papers WHERE id=?',(paper_id,)).fetchone())}
    def confirm_numbers(self,paper_id,body):
        from app.errors import ServiceError
        numbers=[str(n).strip() for n in body.get('numbers',[]) if str(n).strip()];scores=body.get('scores',[])
        if not numbers:raise ValueError('至少需要一个题号')
        with self.database.session(write=True) as conn:
            paper=conn.execute('SELECT archived_at FROM papers WHERE id=?',(paper_id,)).fetchone()
            if not paper:raise ValueError('试卷不存在')
            if paper[0]:raise ValueError('请先恢复已归档试卷')
            if conn.execute('SELECT count(*) FROM questions WHERE paper_id=?',(paper_id,)).fetchone()[0]:raise ServiceError('这张试卷已经有题目记录',409)
            created=now_iso()
            for idx,number in enumerate(numbers):
                raw=scores[idx] if idx<len(scores) else scores[0] if scores else 0
                try:score=float(raw or 0)
                except (TypeError,ValueError):score=0
                conn.execute('INSERT INTO questions(id,paper_id,number,subject,stem,max_score,correctness,review_status,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                    (f'{paper_id}-q-{idx+1:02d}',paper_id,number,body.get('subject') or '数学一',f'第 {number} 题（待补充题干）',score,'unknown','待诊断',created))
            conn.execute("UPDATE papers SET import_status='analyzed',updated_at=? WHERE id=?",(created,paper_id))
            return {'paper_id':paper_id,'created_questions':len(numbers),'status':'analyzed'}

    def correct_questions(self,paper_id,body):
        from app.errors import ServiceError
        if body.get('confirmed') is not True:raise ValueError('请明确确认题号纠正')
        with self.database.session(write=True) as conn:
            paper=conn.execute('SELECT * FROM papers WHERE id=?',(paper_id,)).fetchone()
            if not paper:raise ServiceError('试卷不存在',404)
            if paper['archived_at']:raise ServiceError('请先恢复已归档试卷',409)
            if not paper['source_path']:raise ValueError('试卷缺少原PDF，不能纠正切分')
            original=paper_path(self.config.data,paper['source_path'],self.config.root)
            if not original.is_file():raise ValueError('原PDF文件缺失，请先恢复原卷')
            old={r['id']:dict(r) for r in conn.execute('SELECT * FROM questions WHERE paper_id=?',(paper_id,))}
            if not old:raise ValueError('尚无切分题，请先使用建立题号入口')
            groups=body['questions'];deleted=body.get('delete_question_ids',[])
            ids=[i for g in groups for i in g['question_ids']]+deleted
            numbers=[g['number'].strip() for g in groups]
            if len(ids)!=len(set(ids)) or set(ids)!=set(old) or len(numbers)!=len(set(numbers)) or not all(numbers):
                raise ValueError('全部现有题目必须且只能分配一次；题号不得重复或为空')
            # A paper with history must not be rewritten underneath reports,
            # attempts, bindings or an in-flight analysis input.
            checks=[('agent_reports','paper_id'),('diagnostic_probes','paper_id')]
            if any(conn.execute('SELECT 1 FROM '+t+' WHERE '+k+'=? LIMIT 1',(paper_id,)).fetchone() for t,k in checks):
                raise ServiceError('试卷已有诊断或练习历史，不能纠正切分',409)
            if conn.execute("SELECT 1 FROM workflow_jobs WHERE paper_id=? AND status IN ('queued','dispatching','running')",(paper_id,)).fetchone():
                raise ServiceError('请先结束或取消当前分析任务',409)
            if conn.execute("SELECT 1 FROM learning_tasks WHERE paper_id=? AND status IN ('queued','running','repairing','result_saved')",(paper_id,)).fetchone():
                raise ServiceError('当前任务仍在使用切分，不能纠正',409)
            if conn.execute('SELECT 1 FROM question_diagnoses d JOIN questions q ON q.id=d.question_id WHERE q.paper_id=?',(paper_id,)).fetchone():
                raise ServiceError('已有诊断的题不能纠正',409)
            if any(q['correctness'] not in (None,'unknown') for q in old.values()) or any(
                conn.execute('SELECT 1 FROM '+table+' h JOIN questions q ON q.id=h.question_id WHERE q.paper_id=? LIMIT 1',(paper_id,)).fetchone()
                for table in ('reviews','learning_events')):
                raise ServiceError('已有评价或学习证据的题不能纠正',409)
            conn.execute('INSERT INTO record_versions VALUES(?,?,?,?,?,?)',('version-'+uuid.uuid4().hex,'question_segmentation',paper_id,
                json.dumps(dict(questions=list(old.values()),source_sha256=hashlib.sha256(original.read_bytes()).hexdigest()),ensure_ascii=False),'用户确认重编号/合并/删除错切题',now_iso()))
            removed=set(deleted);kept=[]
            for group,number in zip(groups,numbers):
                rows_=[old[i] for i in group['question_ids']];qid=rows_[0]['id'];kept.append(qid)
                removed.update(r['id'] for r in rows_[1:])
                regions=[]
                for row in rows_:
                    for region in json.loads(row['regions_json'] or '[]'):
                        if region not in regions:regions.append(region)
                regions.sort(key=lambda r:(r['page'],r['bbox'][1],r['bbox'][0]))
                text='\n'.join(r['stem'] or '' for r in rows_)
                conn.execute('''UPDATE questions SET number=?,stem=?,source_text=?,regions_json=?,page_start=?,page_end=?,bbox_json=?,
                    match_bank_id=NULL,match_score=0 WHERE id=?''',(number,text,text,json.dumps(regions,ensure_ascii=False),
                    regions[0]['page'] if regions else None,regions[-1]['page'] if regions else None,
                    json.dumps(regions[0]['bbox']) if regions else None,qid))
            for qid in removed:conn.execute('DELETE FROM questions WHERE id=?',(qid,))
            self._rematch_saved(conn,paper)
            conn.execute('UPDATE papers SET updated_at=? WHERE id=?',(now_iso(),paper_id))
            return dict(paper_id=paper_id,question_ids=kept,deleted_question_ids=sorted(removed),status='corrected')
