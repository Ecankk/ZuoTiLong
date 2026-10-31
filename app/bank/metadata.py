"""Audited corrections of generated source navigation, never problem content."""
from app.storage.boundaries import table_exists
import json
import uuid
import hashlib
from pathlib import Path
from app.knowledge.catalog import digest,encode
from app.bank.annotations import materials


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS bank_metadata_revisions(
        request_id TEXT PRIMARY KEY,bank_id TEXT NOT NULL REFERENCES bank_questions(id),
        payload_sha256 TEXT NOT NULL,before_revision TEXT NOT NULL,after_revision TEXT NOT NULL,
        before_json TEXT NOT NULL,after_json TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL)''')


def _state(conn,bank_id):
    question=conn.execute('SELECT stem,tags_json,fingerprint_json FROM bank_questions WHERE id=?',(bank_id,)).fetchone()
    resource=conn.execute('SELECT metadata_json FROM bank_resources WHERE bank_id=?',(bank_id,)).fetchone()
    if not question or not resource:raise ValueError('只能校正已有图片题源的导航信息')
    return {**dict(question),'metadata_json':resource['metadata_json']}


def correct_navigation(conn,data,bank_id,body):
    from app.common import now_iso
    if body.get('confirmed') is not True:raise ValueError('请明确确认校正题源导航；不会改写题图、参考或旧作答')
    try:request_id=str(uuid.UUID(body['request_id']))
    except (KeyError,TypeError,ValueError,AttributeError):raise ValueError('导航校正请求标识无效') from None
    topic=body.get('topic');reason=body.get('reason');expected=body.get('expected_material_revision')
    if not isinstance(topic,str) or not 1<=len(topic.strip())<=160 or any(ord(c)<32 for c in topic):raise ValueError('导航分类须为1–160字单行文字')
    if not isinstance(reason,str) or not 8<=len(reason.strip())<=1500:raise ValueError('须记录8–1500字的具体校正依据')
    if not isinstance(expected,str) or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):raise ValueError('须提供核查时的完整材料版本')
    payload={'bank_id':bank_id,'topic':topic.strip(),'reason':reason.strip(),'expected_material_revision':expected}
    old=conn.execute('SELECT * FROM bank_metadata_revisions WHERE request_id=?',(request_id,)).fetchone()
    if old:
        if old['payload_sha256']!=digest(payload):raise ValueError('同一校正请求不能更换题目、内容或依据')
        return {'request_id':request_id,'bank_id':bank_id,'reused':True,'before_revision':old['before_revision'],
                'after_revision':old['after_revision'],'still_current':digest(materials(conn,data,bank_id))==old['after_revision']}
    before=_state(conn,bank_id);source=materials(conn,data,bank_id)
    if digest(source)!=expected:raise ValueError('题目材料已变化，请重新核对后校正导航')
    metadata=json.loads(before['metadata_json']);identity=conn.execute('SELECT * FROM bank_identity WHERE bank_id=?',(bank_id,)).fetchone()
    if not identity or identity['math_type'] not in (1,2,3):raise ValueError('题源类别/题号身份不完整，不能生成导航标题')
    label={1:'数学一',2:'数学二',3:'数学三'}[identity['math_type']]
    old_topic=metadata.get('knowledge_point') or '待提取'
    stem=f"{identity['year']} {label} 第{identity['number']}题 · {old_topic}"
    if before['stem']!=stem or not source['question'].get('image_sha256'):raise ValueError('该字段不是自动生成的图片题导航标题，不能通过导航校正改写实际题干')
    if payload['topic']==old_topic:raise ValueError('导航分类没有变化，无需另存校正')
    tags=json.loads(before['tags_json'] or '[]')
    if not isinstance(tags,list) or any(not isinstance(tag,str) for tag in tags):raise ValueError('题源标签格式不合法')
    updated_tags=list(dict.fromkeys(payload['topic'] if tag==old_topic else tag for tag in tags))
    if not updated_tags:updated_tags=[payload['topic']]
    # Correct only the source-generated seed, not a curated mathematical fingerprint.
    fingerprint=json.loads(before['fingerprint_json'] or '{}')
    if fingerprint=={'objects':[old_topic]}:fingerprint={'objects':[payload['topic']]}
    metadata['knowledge_point']=payload['topic']
    after={'stem':f"{identity['year']} {label} 第{identity['number']}题 · {payload['topic']}",
           'tags_json':json.dumps(updated_tags,ensure_ascii=False),'fingerprint_json':json.dumps(fingerprint,ensure_ascii=False),
           'metadata_json':json.dumps(metadata,ensure_ascii=False)}
    conn.execute('UPDATE bank_questions SET stem=?,tags_json=?,fingerprint_json=? WHERE id=?',
                 (after['stem'],after['tags_json'],after['fingerprint_json'],bank_id))
    conn.execute('UPDATE bank_resources SET metadata_json=? WHERE bank_id=?',(after['metadata_json'],bank_id))
    revision=digest(materials(conn,data,bank_id))
    history_after={**after,'image_sha256':{role:source.get(role,{}).get('image_sha256') for role in ('question','analysis','answer')},
                   'reference_text':{role:source.get(role,{}).get('text','') for role in ('analysis','answer')}}
    conn.execute('INSERT INTO bank_metadata_revisions VALUES(?,?,?,?,?,?,?,?,?)',
        (request_id,bank_id,digest(payload),expected,revision,encode(before),encode(history_after),payload['reason'],now_iso()))
    return {'request_id':request_id,'bank_id':bank_id,'reused':False,'before_revision':expected,
            'after_revision':revision,'still_current':True,'requires_annotation_review':True}


def preserve_on_import(conn,data,bank_id,source_paths,*,source_answer=None):
    """Keep a reviewed local label only with exactly the same image version.

    Run before copying this question's source files. Changed questions or
    references need review rather than inheriting the old correction.
    """
    if not table_exists(conn, 'bank_metadata_revisions'):return False
    row=conn.execute('SELECT after_json FROM bank_metadata_revisions WHERE bank_id=? ORDER BY rowid DESC LIMIT 1',(bank_id,)).fetchone()
    if not row:return False
    saved=json.loads(row['after_json']);current=_state(conn,bank_id)
    if current!={k:saved[k] for k in current}:raise ValueError('已校正题目的当前导航另有变化，不能由旧题源覆盖：'+bank_id)
    actual=materials(conn,data,bank_id)
    incoming_answer='' if source_answer is None else str(source_answer)
    if incoming_answer!=saved['reference_text']['answer'] or any(actual.get(role,{}).get('text','')!=saved['reference_text'][role] for role in ('analysis','answer')):
        raise ValueError('已校正题目的参考正文版本变化，须独立核验，不能覆盖：'+bank_id)
    for role in ('question','analysis','answer'):
        path=source_paths.get(role);incoming=hashlib.sha256(Path(path).read_bytes()).hexdigest() if path and Path(path).is_file() else None
        if incoming!=saved['image_sha256'][role] or actual.get(role,{}).get('image_sha256')!=saved['image_sha256'][role]:
            raise ValueError('已校正题目的题图或参考版本变化，须独立核验，不能覆盖：'+bank_id)
    return True
