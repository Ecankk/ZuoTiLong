"""Audited textual corrections; original provenance is never rewritten."""
import json,re
from copy import deepcopy
from pathlib import Path
from app.bank import source_records as records

FIELDS={'match','role','find','replace','reason','evidence'}

def apply(batch,path):
    doc=json.loads(Path(path).read_text(encoding='utf8'))
    if not isinstance(doc,dict) or set(doc)!={'schema','source_id','revision','entries'} or doc['schema']!='mathlens.bank-errata/v1':raise ValueError('勘误格式无效')
    if (doc['source_id'],doc['revision'])!=(batch[0]['source_id'],batch[0]['revision']):raise ValueError('勘误来源/版本不匹配')
    if not isinstance(doc['entries'],list):raise ValueError('勘误entries必须是列表')
    values=deepcopy(batch);by_uid={r['source_uid']:r for r in values}
    for e in doc['entries']:
        if (not isinstance(e,dict) or set(e)!=FIELDS or not isinstance(e['match'],dict) or set(e['match'])!={'source_uid'}
            or not isinstance(e['match']['source_uid'],str) or not e['match']['source_uid'].strip()
            or any(not isinstance(e[k],str) for k in ('role','find','replace','reason','evidence'))
            or not e['find'] or not all(e[k].strip() for k in ('reason','evidence'))):raise ValueError('勘误字段、find、reason或evidence无效')
        row=by_uid.get(e['match']['source_uid'])
        if row is None:raise ValueError('勘误未匹配来源题目：'+str(e['match']['source_uid']))
        role=e['role']
        if role in ('stem','answer','analysis'):part=row[role]
        elif role.startswith('option:'):
            option=next((o for o in row['options'] if o['label']==role[7:]),None)
            if not option:raise ValueError('勘误选项不存在：'+role)
            part=option['content']
        else:raise ValueError('勘误角色无效：'+role)
        if part['text'].count(e['find'])!=1:raise ValueError(f"勘误find必须恰好出现一次：{row['source_uid']} {role}")
        part['text']=part['text'].replace(e['find'],e['replace'],1);part['sha256']=records.sha256(part['text'].encode('utf8'))
        row.setdefault('errata',[]).append(deepcopy(e))
    return values,doc

def markers(conn,bid):
    row=conn.execute('SELECT metadata_json FROM bank_resources WHERE bank_id=?',(bid,)).fetchone()
    return public(json.loads(row[0]).get('errata',[])) if row else []

def public(entries):
    return [{k:e[k] for k in ('role','reason','evidence')} for e in entries]

def apply_existing(config,path,collection,confirm=None):
    """The same preview/apply pipeline for legacy IDs and already-imported sources."""
    import tempfile,shutil
    from app.bank import collection_packs as packs,source_import
    from app.common import now_iso
    doc=json.loads(Path(path).read_text(encoding='utf8'))
    if not isinstance(doc.get('entries'),list) or not doc['entries']:raise ValueError('勘误至少需要一个条目')
    with tempfile.TemporaryDirectory(prefix='mathlens-errata-') as folder:
        root=Path(folder)
        def prepare(conn):
            assets={};batch=[];ids={};baselines={}
            for uid in dict.fromkeys(e['match']['source_uid'] for e in doc['entries']):
                stored=conn.execute('SELECT bank_id FROM bank_source_records WHERE source_id=? AND source_uid=?',(doc['source_id'],uid)).fetchone()
                bid=stored[0] if stored else uid
                row=conn.execute('SELECT * FROM bank_questions WHERE id=?',(bid,)).fetchone()
                if not row or row['collection_id']!=collection:raise ValueError('勘误未匹配目标题集：'+uid)
                item=packs._export_record(conn,config,row,assets);record=item['record']
                if (record['source_id'],record['revision'])!=(doc['source_id'],doc['revision']):raise ValueError('勘误来源/版本不匹配；既有S01版本为legacy-db-export/v1')
                baselines[bid]=deepcopy(record);ids[(record['source_id'],record['source_uid'])]=bid;batch.append(record)
            for name,source in assets.items():
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            pending={**doc,'entries':[e for e in doc['entries'] if not any(r['source_uid']==e['match']['source_uid'] and e in r.get('errata',[]) for r in batch)]}
            pending_path=root/'pending.json';pending_path.write_text(records.canonical(pending),encoding='utf8')
            corrected,_=apply(batch,pending_path)
            for record in corrected:records.validate(record,root)
            report=source_import.preview(conn,corrected,doc,[],[],collection,bank_ids=ids,baselines=baselines)
            return corrected,ids,baselines,report
        with packs.connection(config) as conn:
            conn.execute('BEGIN');batch,ids,baselines,report=prepare(conn)
        if confirm is None:return dict(report,applied=False)
        if confirm!=report['plan_sha256']:raise ValueError('预演已过期，请重新预演')
        from app.storage.library_backup import backup_library
        backup=backup_library(config.library_dir,workspaces=(config.data,))
        with packs.connection(config,True) as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                batch,ids,baselines,locked=prepare(conn)
                if locked['plan_sha256']!=confirm:raise ValueError('备份期间题库变化，请重新预演')
                for bid,baseline in baselines.items():
                    conn.execute('INSERT OR IGNORE INTO bank_source_versions VALUES(?,?,?,?,?)',(bid,records.digest([baseline,[]]),records.canonical(baseline),'[]',now_iso()))
                pixels={r['bank_id']:r['sha256'] for r in conn.execute('SELECT bank_id,sha256 FROM bank_identity')}
                source_import._apply(conn,config,batch,report,root,bank_ids=ids,initialize_schema=False)
                for record in batch:
                    bid=ids[(record['source_id'],record['source_uid'])]
                    if bid in report['updated'] and record['stem']['images'] and record['stem']['images']==baselines[bid]['stem']['images']:
                        conn.execute('UPDATE bank_identity SET sha256=? WHERE bank_id=?',(pixels.get(bid),bid))
                conn.commit()
            except BaseException:conn.rollback();raise
        return dict(report,applied=True,backup=backup)
