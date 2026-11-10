"""Deterministic S03 chapter-local metadata; never replace corrected materials."""
import copy,json,re
from app.bank.source_records import canonical,digest
from app.common import now_iso

REVISION='19f626daefe25fe0e0d76abc30413b697fe4ce24'


def number(record):
    if record.get('source_id')!='S03' or record.get('revision')!=REVISION:return None
    book=record.get('book') or {}
    if book.get('part')!='强化篇':return None
    match=re.fullmatch(r'chapters/chapter-(\d{2})\.html#q([1-9]\d*)',record.get('source_uid',''))
    if not match or not 32<=int(match[1])<=67:return None
    locator=record.get('locator') or {}
    if locator.get('path')!=f'chapters/chapter-{match[1]}.html' or locator.get('pointer')!='#q'+match[2]:return None
    if book.get('locator')!=record['source_uid']:return None
    return match[2]


def number_only(old,record,changes):
    """Only the approved null → verified local-number enrichment qualifies."""
    before=json.loads(old['record_json']);expected=copy.deepcopy(before)
    n=number(before)
    if not n or before['book']['number'] is not None:return False
    expected['book']['number']=n
    return record==expected and json.loads(old.get('overrides_json','[]'))==changes


def initialize(conn):
    cursor=conn.execute("SELECT s.*,r.metadata_json FROM bank_source_records s JOIN bank_resources r ON r.bank_id=s.bank_id WHERE s.source_id='S03'")
    names=[c[0] for c in cursor.description];changed=[]
    for raw in cursor.fetchall():
        row=dict(zip(names,raw));record=json.loads(row['record_json']);n=number(record)
        if not n or record['book']['number'] is not None:continue
        metadata=json.loads(row['metadata_json']);book=metadata.get('book') or {}
        if book.get('number') not in (None,n):continue
        record['book']['number']=n
        # Keep every erratum, source text and any manually corrected navigation.
        metadata['book']={**book,'number':n}
        sha=digest([record,json.loads(row['overrides_json'])]);text=canonical(record)
        conn.execute('UPDATE bank_resources SET metadata_json=? WHERE bank_id=?',(canonical(metadata),row['bank_id']))
        conn.execute('UPDATE bank_source_records SET record_json=?,record_sha256=? WHERE bank_id=?',(text,sha,row['bank_id']))
        conn.execute('INSERT OR IGNORE INTO bank_source_versions VALUES(?,?,?,?,?)',(row['bank_id'],sha,text,row['overrides_json'],now_iso()))
        changed.append(row['bank_id'])
    return changed
