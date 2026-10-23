"""Personal exam exposure policy. Teaching choices remain the Agent's job."""
import hashlib
import json
import re
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def init_access(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS preferences(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS bank_identity(bank_id TEXT PRIMARY KEY,math_type INTEGER,year TEXT,number INTEGER,sha256 TEXT);
    CREATE TABLE IF NOT EXISTS bank_links(left_id TEXT,right_id TEXT,reason TEXT NOT NULL,PRIMARY KEY(left_id,right_id));
    CREATE TABLE IF NOT EXISTS bank_views(bank_id TEXT,role TEXT,created_at TEXT,PRIMARY KEY(bank_id,role));
    CREATE TABLE IF NOT EXISTS bank_cross_reviews(bank_id TEXT,study_type INTEGER,sha256 TEXT,reason TEXT,PRIMARY KEY(bank_id,study_type));
    ''')
    conn.execute("INSERT OR IGNORE INTO preferences VALUES(1,?)",(json.dumps({'study_type':1,'reserved':[]}),))
    for row in conn.execute('SELECT id FROM bank_questions'):
        match=re.fullmatch(r'math([123])-(\d{4})-(\d+)',row[0])
        conn.execute('INSERT OR IGNORE INTO bank_identity VALUES(?,?,?,?,NULL)',(row[0],int(match[1]) if match else 0,match[2] if match else '',int(match[3]) if match else 0))


def preferences(conn):
    return {'mask_same_type': True, **json.loads(conn.execute('SELECT payload FROM preferences WHERE id=1').fetchone()[0])}


def save_preferences(conn, body):
    if body.get('study_type') not in (1,2,3):raise ValueError('请选择数学一、二或三')
    mask_same_type = body.get('mask_same_type', preferences(conn)['mask_same_type'])
    if type(mask_same_type) is not bool:raise ValueError('检验题隐藏选项需要是开关值')
    reserved=body.get('reserved',[])
    if not isinstance(reserved,list) or len(reserved)>150:raise ValueError('预留范围格式不合法')
    for item in reserved:
        if not isinstance(item,dict) or set(item)!={'math_type','year'} or item['math_type'] not in (1,2,3) or not re.fullmatch(r'\d{4}',str(item['year'])):
            raise ValueError('预留卷需要数学类别和四位年份')
    value={'study_type':body['study_type'],'mask_same_type':mask_same_type,'reserved':[{'math_type':v['math_type'],'year':str(v['year'])} for v in reserved]}
    conn.execute('UPDATE preferences SET payload=? WHERE id=1',(json.dumps(value),))
    return value


def register_identity(conn, bid, math_type, year, number, path):
    from PIL import Image
    with Image.open(path) as image:
        # Exact decoded pixels, also recognising the same image with different PNG metadata.
        rgb=image.convert('RGB');digest=hashlib.sha256(str(rgb.size).encode()+rgb.tobytes()).hexdigest()
    conn.execute('INSERT INTO bank_identity VALUES(?,?,?,?,?) ON CONFLICT(bank_id) DO UPDATE SET math_type=excluded.math_type,year=excluded.year,number=excluded.number,sha256=excluded.sha256',(bid,math_type,str(year),number,digest))


def aliases(conn,bid):
    group={bid}
    changed=True
    identities=list(conn.execute('SELECT bank_id,sha256 FROM bank_identity'))
    links=list(conn.execute('SELECT left_id,right_id FROM bank_links'))
    while changed:
        old=len(group)
        digests={r['sha256'] for r in identities if r['bank_id'] in group and r['sha256']}
        group.update(r['bank_id'] for r in identities if r['sha256'] in digests)
        for left,right in links:
            if left in group or right in group:group.update((left,right))
        changed=len(group)!=old
    return group


def access(conn,bid):
    row=conn.execute('SELECT * FROM bank_identity WHERE bank_id=?',(bid,)).fetchone()
    if not row:raise ValueError('题库题目不存在')
    meta=dict(row);policy=preferences(conn);group=aliases(conn,bid)
    related=[dict(r) for r in conn.execute('SELECT * FROM bank_identity') if r['bank_id'] in group]
    reserved=any({'math_type':r['math_type'],'year':r['year']} in policy['reserved'] for r in related)
    views=[dict(r) for r in conn.execute('SELECT * FROM bank_views') if r['bank_id'] in group]
    confirmed=any(v['role']=='question' for v in views)
    reviewed=conn.execute('SELECT sha256 FROM bank_cross_reviews WHERE bank_id=? AND study_type=?',(bid,policy['study_type'])).fetchone()
    cross_safe=bool(meta['math_type'] and meta['math_type']!=policy['study_type'] and reviewed and reviewed[0] and reviewed[0]==meta['sha256'] and not any(r['math_type']==policy['study_type'] for r in related))
    masked=policy['mask_same_type'] and meta['math_type']==policy['study_type']
    allowed=not reserved and (not masked or confirmed)
    return {'id':bid,'math_type':meta['math_type'],'year':meta['year'],'number':meta['number'],
            'reserved':reserved,'can_view':allowed,'confirmed':confirmed,'cross_checked':cross_safe,'masked':masked,
            'analysis_allowed':allowed and any(v['role']=='analysis' for v in views),
            'reason':'用户预留整卷，不用于针对性检验' if reserved else '' if allowed else '当前备考类别的检验题已隐藏，确认后查看'}


def require_access(conn,bid,role='question',internal=False):
    state=access(conn,bid)
    if state['reserved'] or (not internal and (not state['can_view'] or role!='question' and not state['analysis_allowed'])):
        raise ValueError(state['reason'] or '请先明确确认查看题目或解析')
    return state


def reveal(conn,bid,role,confirmed):
    if confirmed is not True or role not in ('question','analysis'):raise ValueError('需要手动确认查看')
    state=access(conn,bid)
    if state['reserved']:raise ValueError(state['reason'])
    if role=='question' and state['math_type'] == preferences(conn)['study_type'] and state['confirmed']:
        return state
    if role=='analysis' and not state['can_view']:raise ValueError('请先确认查看题干')
    for item in aliases(conn,bid):
        conn.execute('INSERT OR IGNORE INTO bank_views VALUES(?,?,?)',(item,role,now()))
        if role=='analysis':conn.execute('INSERT OR IGNORE INTO bank_exposures VALUES(?,?)',(item,now()))
    return access(conn,bid)


def record_view(conn,bid,role):
    """Track actual image loads without granting probe reveal permission."""
    if role not in ('question','analysis','answer'):raise ValueError('资源类别不合法')
    if not conn.execute('SELECT bank_id FROM bank_identity WHERE bank_id=?',(bid,)).fetchone():raise ValueError('题库题目不存在')
    for item in aliases(conn,bid):
        conn.execute('INSERT OR IGNORE INTO bank_views VALUES(?,?,?)',(item,'seen_question' if role=='question' else 'analysis',now()))
        if role!='question':conn.execute('INSERT OR IGNORE INTO bank_exposures VALUES(?,?)',(item,now()))


def public_bank(conn,bid,view='probe'):
    if view=='library':
        row=conn.execute('SELECT b.*,i.math_type,i.year,i.number FROM bank_questions b JOIN bank_identity i ON i.bank_id=b.id WHERE b.id=?',(bid,)).fetchone()
        if not row:raise ValueError('题库题目不存在')
        return {'id':bid,'math_type':row['math_type'],'year':row['year'],'number':row['number'],
                'can_view':True,'reserved':{'math_type':row['math_type'],'year':row['year']} in preferences(conn)['reserved'],
                'reason':'','analysis_allowed':True,'stem':row['stem'],'tags':json.loads(row['tags_json'] or '[]'),
                'question_image':f'/api/bank/{bid}/question?view=library','analysis_image':f'/api/bank/{bid}/analysis?view=library'}
    state=access(conn,bid)
    if not state['can_view']:return state
    row=conn.execute('SELECT * FROM bank_questions WHERE id=?',(bid,)).fetchone()
    return {**state,'stem':row['stem'],'tags':json.loads(row['tags_json'] or '[]'),
            'question_image':f'/api/bank/{bid}/question',
            **({'analysis_image':f'/api/bank/{bid}/analysis','answer':row['answer'],'explanation':row['explanation']} if state['analysis_allowed'] else {})}


def review_cross(conn,bid,reason,distinct=True,other_id=None):
    require_access(conn,bid,internal=True)
    if not isinstance(reason,str) or len(reason.strip())<8:raise ValueError('请提供具体的题目核对依据')
    if other_id:
        require_access(conn,other_id,internal=True)
        if distinct is False:conn.execute('INSERT OR REPLACE INTO bank_links VALUES(?,?,?)',(bid,other_id,reason))
    row=conn.execute('SELECT sha256 FROM bank_identity WHERE bank_id=?',(bid,)).fetchone()
    if distinct and row[0]:conn.execute('INSERT OR REPLACE INTO bank_cross_reviews VALUES(?,?,?,?)',(bid,preferences(conn)['study_type'],row[0],reason))
    return access(conn,bid)
