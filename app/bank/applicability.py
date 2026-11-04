"""Source applicability is separate from an original exam identity."""
import json
from app.bank.source_records import digest,canonical
from app.common import now_iso

def math_types(value,identity=None):return json.loads(value or '[]') or ([identity] if identity in (1,2,3) else [])

def book_key(book,bid):
    import re
    def natural(value):return tuple((1,int(v)) if v.isdecimal() else (0,v) for v in re.split(r'(\d+)',str(value or '')))
    locator=book.get('locator') or '';chapter=re.search(r'chapter-(\d+)',locator);number=re.search(r'#q(\d+)',locator)
    return (natural(book.get('part')),natural(chapter[1] if chapter else book.get('chapter')),natural(book.get('number') or (number[1] if number else locator)),bid)

def initialize(conn):
    if 'math_types_json' not in {r[1] for r in conn.execute('PRAGMA table_info(bank_questions)')}:
        conn.execute("ALTER TABLE bank_questions ADD COLUMN math_types_json TEXT NOT NULL DEFAULT '[]'")
        conn.execute("""UPDATE bank_questions SET math_types_json='['||(SELECT math_type FROM bank_identity WHERE bank_id=id)||']'
            WHERE math_types_json='[]' AND id IN (SELECT bank_id FROM bank_identity WHERE math_type IN (1,2,3))""")
    cursor=conn.execute("SELECT * FROM bank_source_records WHERE source_id='S03'")
    names=[v[0] for v in cursor.description]
    for raw in cursor.fetchall():
        row=dict(zip(names,raw))
        record=json.loads(row['record_json'])
        if record['revision']!='19f626daefe25fe0e0d76abc30413b697fe4ce24':continue
        if not record['locator']['path'].startswith('chapters/chapter-'):continue
        chapter=int(record['locator']['path'].split('chapter-')[1].split('.')[0])
        if not 32<=chapter<=67:continue
        conn.execute("UPDATE bank_questions SET math_types_json='[1]' WHERE id=? AND math_types_json!='[1]'",(row['bank_id'],))
        if record.get('math_types')==[1]:continue
        record['math_types']=[1];sha=digest([record,json.loads(row['overrides_json'])]);text=canonical(record)
        conn.execute('UPDATE bank_source_records SET record_json=?,record_sha256=? WHERE bank_id=?',(text,sha,row['bank_id']))
        conn.execute('INSERT OR IGNORE INTO bank_source_versions VALUES(?,?,?,?,?)',(row['bank_id'],sha,text,row['overrides_json'],now_iso()))
