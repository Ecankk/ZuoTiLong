"""Read receipts are personal metadata, separate from immutable assessments."""
import json
from app.common import now_iso
from app.errors import ServiceError
from app.knowledge.catalog import digest

SOURCES=('paper_practice','profile_practice','free_practice')

def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS feedback_read_receipts(
        request_id TEXT PRIMARY KEY,source TEXT NOT NULL,attempt_id TEXT NOT NULL,
        feedback_revision TEXT NOT NULL,read_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_feedback_read ON feedback_read_receipts(source,attempt_id,feedback_revision)')

def effective(value):
    value=json.loads(value) if isinstance(value,str) else value
    return value if value and value.get('method')!='explicit_answer_match' else None

def info(conn,source,aid,assessment):
    assessment=effective(assessment)
    revision=(assessment.get('task_result_id') or digest(assessment)) if assessment else None
    read=conn.execute('SELECT min(read_at) FROM feedback_read_receipts WHERE source=? AND attempt_id=? AND feedback_revision=?',
        (source,aid,revision)).fetchone()[0] if revision else None
    return dict(feedback_revision=revision,feedback_unread=bool(revision and not read),feedback_read_at=read)

def mark(conn,body):
    source,aid,revision=(body[k] for k in ('source','attempt_id','feedback_revision'))
    if source not in SOURCES:raise ValueError('反馈来源不合法')
    previous=conn.execute('SELECT * FROM feedback_read_receipts WHERE request_id=?',(body['request_id'],)).fetchone()
    if previous:
        if tuple(previous[k] for k in ('source','attempt_id','feedback_revision'))!=(source,aid,revision):raise ServiceError('request_id 已用于其他反馈',409)
        return dict(attempt_id=aid,feedback_revision=revision,read_at=previous['read_at'],unread=False,reused=True)
    table={'paper_practice':'probe_attempts','free_practice':'free_practice_attempts','profile_practice':'profile_practice_attempts'}[source]
    exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
    row=conn.execute('SELECT assessment_json FROM '+table+' WHERE id=?',(aid,)).fetchone() if exists else None
    if not row:raise ServiceError('作答不存在或反馈来源不符',404)
    state=info(conn,source,aid,row[0])
    if not state['feedback_revision'] or state['feedback_revision']!=revision:raise ServiceError('当前批改反馈已变化或尚不可用，请刷新',409)
    read_at=state['feedback_read_at'] or now_iso()
    conn.execute('INSERT INTO feedback_read_receipts VALUES(?,?,?,?,?)',(body['request_id'],source,aid,revision,read_at))
    return dict(attempt_id=aid,feedback_revision=revision,read_at=read_at,unread=False,reused=not state['feedback_unread'])
