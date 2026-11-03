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

        bank_rows = []
        for item in rows(conn, "SELECT * FROM bank_questions"):
            item["tags"] = json_load(item.pop("tags_json", None), [])
            item["fingerprint"] = json_load(item.pop("fingerprint_json", None), {})
            bank_rows.append(item)
        write_progress(self.config.data,paper_id,status='running',phase='opening',pages_done=0,pages_total=None,
                       questions=0,warnings=[],message='正在读取原PDF')
        try:
            result = extract_pdf(pdf_path,cache_root=self.config.data/'ocr-cache',
                                 on_progress=lambda **fields:write_progress(self.config.data,paper_id,**fields))
        except Exception as exc:
            write_progress(self.config.data,paper_id,status='failed',message=str(exc))
            raise
        extracted = match_bank_questions(result["questions"], bank_rows)
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

    def import_pdf(self,filename,content,fields):
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
                job=enqueue(conn,self.config.root,self.config.data,'analyze_paper',paper_id,
                    str(uuid.uuid5(uuid.NAMESPACE_URL,'mathlens:paper:'+digest)),auto_prepare=True,index_after=True,practice_contract_version='1.9',contract_version='2.0')
                result.update(agent_queued=True,job_id=job['id'])
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
