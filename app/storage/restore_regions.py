"""Explicit, backed-up repair from an existing OCR cache; never runs OCR."""
from contextlib import closing
from pathlib import Path
import hashlib,json,sqlite3,uuid
from app.documents.pdf import PIPELINE_VERSION,segment_pages
from app.storage.paths import paper_path
from app.learning.tasks import digest,encode
from app.common import now_iso

def connect(config,write=False):
    conn=sqlite3.connect(config.database.resolve().as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=15)
    conn.row_factory=sqlite3.Row
    return conn

def preview(conn,config,paper_id):
    paper=conn.execute('SELECT * FROM papers WHERE id=?',(paper_id,)).fetchone()
    if not paper:raise ValueError('试卷不存在')
    pdf=paper_path(config.data,paper['source_path'],config.root)
    source=hashlib.sha256(pdf.read_bytes()).hexdigest();folder=config.data/'ocr-cache'/source
    cache=next((p for p in (folder/f'{PIPELINE_VERSION}-ocr.json',folder/f'{PIPELINE_VERSION}-text.json') if p.is_file()),None)
    if not cache:raise ValueError('未找到当前原PDF对应的本地识别缓存；不重新运行OCR')
    raw=cache.read_bytes();pages=json.loads(raw)['pages'];questions,warnings=segment_pages(pages)
    by_number={}
    for q in questions:by_number.setdefault(str(q['number']),[]).append(q)
    changed=[];unchanged=[];missing=[];ambiguous=[];old=[]
    for row in conn.execute('SELECT id,number,regions_json,page_start,page_end,bbox_json FROM questions WHERE paper_id=? ORDER BY id',(paper_id,)):
        old.append(dict(row));matches=by_number.get(str(row['number']),[])
        if not matches:missing.append(dict(question_id=row['id'],number=row['number'],reason='cache_missing_number_keep_existing'));continue
        if len(matches)!=1:ambiguous.append(dict(question_id=row['id'],number=row['number']));continue
        regions=matches[0]['regions']
        if regions==json.loads(row['regions_json'] or '[]'):unchanged.append(row['id']);continue
        changed.append(dict(question_id=row['id'],number=row['number'],old_regions=json.loads(row['regions_json'] or '[]'),new_regions=regions))
    report=dict(paper_id=paper_id,source_sha256=source,cache_sha256=hashlib.sha256(raw).hexdigest(),
                changed=changed,unchanged=unchanged,missing=missing,ambiguous=ambiguous,warnings=warnings)
    report['plan_sha256']=digest(dict(report=report,rows=old))
    return report

def restore(config,paper_id,confirm=None):
    with closing(connect(config)) as conn:report=preview(conn,config,paper_id)
    if confirm is None:return dict(report,applied=False)
    if confirm!=report['plan_sha256']:raise ValueError('预演摘要已过期，请重新--dry-run')
    if report['ambiguous']:raise ValueError('缓存中存在同号多候选，不能自动恢复')
    if not report['changed']:return dict(report,applied=False,backup=None)
    with closing(connect(config,True)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            if preview(conn,config,paper_id)['plan_sha256']!=confirm:raise ValueError('切分/缓存已变化，请重新预演')
            for table in ('workflow_jobs','learning_tasks'):
                if conn.execute(f"SELECT 1 FROM {table} WHERE paper_id=? AND status IN ('queued','dispatching','running','repairing','result_saved')",(paper_id,)).fetchone():raise ValueError('试卷仍有活动任务，请先完成或取消')
            folder=config.data/'backups';folder.mkdir(parents=True,exist_ok=True)
            backup=folder/('segmentation-regions-before-'+uuid.uuid4().hex+'.sqlite3')
            from app.storage.backup_archive import snapshot
            snapshot(config.database,backup)
            conn.execute('INSERT INTO record_versions VALUES(?,?,?,?,?,?)',('version-'+uuid.uuid4().hex,'question_regions_restore',paper_id,encode(report),'显式确认从本地识别缓存恢复区域',now_iso()))
            for item in report['changed']:
                regions=item['new_regions']
                conn.execute('UPDATE questions SET regions_json=?,page_start=?,page_end=?,bbox_json=? WHERE id=?',
                    (json.dumps(regions,ensure_ascii=False),regions[0]['page'] if regions else None,regions[-1]['page'] if regions else None,json.dumps(regions[0]['bbox']) if regions else None,item['question_id']))
            conn.execute('UPDATE papers SET updated_at=? WHERE id=?',(now_iso(),paper_id));conn.commit()
        except BaseException:conn.rollback();raise
    return dict(report,applied=True,backup=str(backup))
