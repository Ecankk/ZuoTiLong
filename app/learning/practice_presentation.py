"""Student projections never rewrite saved mathematical evidence."""
import json
from app.knowledge.catalog import digest

PLACEHOLDERS={'参考解析见原图','参考答案见原图','解析见原图','答案见原图'}

def placeholder(text):return isinstance(text,str) and text.strip().rstrip('。.！!') in PLACEHOLDERS

def reference(value,extra=None):
    fields=('analysis_text','answer_text','solution_note','reference_reasoning','explanation')
    combined={**(extra or {}),**value}
    available=any(combined.get(k) for k in ('analysis_image','answer_image')) or any(isinstance(combined.get(k),str) and combined[k].strip() and not placeholder(combined[k]) for k in fields)
    return {k:None if k in fields and placeholder(v) and available else v for k,v in value.items()}

def metadata(conn,bid):
    row=conn.execute('''SELECT b.collection_id,c.name,r.metadata_json FROM bank_questions b
        JOIN bank_collections c ON c.id=b.collection_id LEFT JOIN bank_resources r ON r.bank_id=b.id WHERE b.id=?''',(bid,)).fetchone()
    if not row:return dict(collection_id=None,collection_label=None,book=None)
    book=json.loads(row['metadata_json'] or '{}').get('book')
    return dict(collection_id=row['collection_id'],collection_label=row['name'],book={k:book.get(k) for k in ('part','chapter','number','locator')} if book else None)

def source_for(conn,data,probe):
    saved=json.loads(probe['payload_json']).get('source_metadata')
    if saved is not None:return saved
    empty=dict(collection_id=None,collection_label=None,book=None)
    from app.learning.practice_knowledge import binding_for
    binding=binding_for(conn,probe['id'])
    if not binding:return empty
    try:
        from app.bank.annotations import materials
        if digest(materials(conn,data,probe['bank_id']))!=binding['material_revision']:return empty
        return metadata(conn,probe['bank_id'])
    except (ValueError,OSError):return empty

def correctness(assessment):
    if not assessment:return None
    status=assessment.get('answer_status')
    if status in ('correct','wrong','partial','unknown'):return status
    return 'correct' if assessment.get('correct') is True else 'wrong' if assessment.get('correct') is False else 'unknown'

def denied(state):
    from app.errors import ServiceError
    reason='reserved' if state['reserved'] else 'masked'
    message='这道题属于预留试卷，暂不用于练习。' if reason=='reserved' else '这道题当前已遮挡，请先确认查看题面。'
    raise ServiceError(message,403,reason=reason)
