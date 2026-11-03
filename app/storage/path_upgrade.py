"""Read-only path inventory and explicitly confirmed, backed-up upgrades."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import re
import ntpath
import os
from datetime import datetime,timezone
from app.bank.source_records import digest
from app.storage.paths import resolve_file

FIELDS={'learning': [('papers','id','source_path','source_sha256'),('answer_images','id','path','sha256')],
        'library':[('bank_resources','bank_id',r+'_path',None) for r in ('question','analysis','answer')],
        'session':[]}


def stores(config):
    return {'learning':config.database,'library':config.library_database,'session':config.data/'agent-session.db'}


def inventory(config):
    entries=[];history=[]
    for owner,db in stores(config).items():
        if not db.is_file():continue
        root=config.library_dir if owner=='library' else config.data
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as conn:
            conn.row_factory=sqlite3.Row
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table,key,field,sha_field in FIELDS[owner]:
                if table not in tables:continue
                columns={r[1] for r in conn.execute('PRAGMA table_info('+table+')')}
                for row in conn.execute('SELECT * FROM '+table):
                    value=row[field]
                    if not value:continue
                    expected=row[sha_field] if sha_field and sha_field in columns else None
                    try:actual=resolve_file(root,value); relative=str(value).replace('\\','/')
                    except ValueError:
                        # Only a unique managed-directory suffix is a candidate;
                        # without a stored content hash it is never confirmed.
                        parts=str(value).replace('\\','/').split('/')
                        markers=('bank-assets','knowledge-sources') if owner=='library' else ('papers','answer-images','practice-materials','memory','agent-input')
                        offsets=[i for i,p in enumerate(parts) if p in markers]
                        relative='/'.join(parts[offsets[0]:]) if len(offsets)==1 else None
                        actual=resolve_file(root,relative) if relative else None
                    if actual and not actual.is_file() and not str(value).replace('\\','/').startswith(('papers/','answer-images/','bank-assets/')):
                        parts=str(value).replace('\\','/').split('/')
                        markers=('bank-assets','knowledge-sources') if owner=='library' else ('papers','answer-images')
                        offsets=[i for i,p in enumerate(parts) if p in markers]
                        if len(offsets)==1:
                            relative='/'.join(parts[offsets[0]:]);actual=resolve_file(root,relative)
                    exists=bool(actual and actual.is_file())
                    changed=relative!=str(value).replace('\\','/')
                    sha=hashlib.sha256(actual.read_bytes()).hexdigest() if exists and (expected or changed) else None
                    try:valid_location=resolve_file(root,value).is_file()
                    except ValueError:valid_location=False
                    verified=bool(exists and expected and expected==sha)
                    entries.append(dict(store=owner,table=table,key=key,id=row[key],field=field,old=value,
                        relative=relative,exists=exists,sha256=sha,expected_sha256=expected,
                        change=changed,valid_location=valid_location,verified=verified,can_migrate=changed and verified))
            # Immutable JSON is evidence, not a live file locator. Inventory it
            # separately rather than invalidating recorded task/material hashes.
            for table in sorted(tables):
                if table.startswith('sqlite_'):continue
                cols=[r[1] for r in conn.execute('PRAGMA table_info("'+table+'")') if r[2].upper()=='TEXT']
                for row in conn.execute('SELECT rowid,* FROM "'+table+'"'):
                    for col in cols:
                        raw=row[col]
                        if not isinstance(raw,str) or not raw.startswith(('{','[')):continue
                        if not re.search(r'(?<![A-Za-z])[A-Za-z]:[\\/]|"/(?:tmp|home|Users)/',raw):continue
                        try:value=json.loads(raw)
                        except ValueError:continue
                        def walk(v,pointer=''):
                            if isinstance(v,dict):
                                for k,x in v.items():yield from walk(x,pointer+'/'+str(k))
                            elif isinstance(v,list):
                                for i,x in enumerate(v):yield from walk(x,pointer+'/'+str(i))
                            elif isinstance(v,str) and '\n' not in v and len(v)<1024 and (Path(v).is_absolute() or len(v)>2 and v[1:3] in (':\\',':/')):
                                yield dict(store=owner,table=table,rowid=row[0],field=col,pointer=pointer,path=v)
                        history.extend(walk(value))
    return entries,history


def preview(config):
    entries,history=inventory(config)
    result=dict(changes=[e for e in entries if e['can_migrate']],
        unresolved=[e for e in entries if e['change'] and not e['can_migrate']],
        invalid_references=[e for e in entries if not e['valid_location'] or e['expected_sha256'] and not e['verified']],
        historical_references=history)
    session_change=_session_change(config)
    if session_change:result['changes'].append(session_change[0])
    marker=config.data/'workspace.json'
    if marker.is_file():
        from app.config import library_location
        value=json.loads(marker.read_text(encoding='utf8'))
        location=library_location(config.data,config.library_dir)
        if Path(value.get('library','')).is_absolute() and Path(value['library'])!=Path(location):
            result['changes'].append(dict(store='config',field='library',old=value['library'],
                relative=location,
                sha256=hashlib.sha256(marker.read_bytes()).hexdigest(),exists=config.library_database.is_file(),verified=True))
    result['plan_sha256']=digest(result)
    return result


def _session_change(config):
    path=config.data/'agent-session.db'
    if not path.is_file():return None
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='session'").fetchone():return None
        row=conn.execute('SELECT payload FROM session WHERE id=1').fetchone()
    if not row:return None
    from app.storage.paths import session_paths
    value=json.loads(row[0]);portable=session_paths(value,config.data)
    if portable==value:return None
    new=json.dumps(portable,ensure_ascii=False)
    return (dict(store='session',table='session',field='payload',id=1,
        old_sha256=hashlib.sha256(row[0].encode()).hexdigest(),new_sha256=hashlib.sha256(new.encode()).hexdigest()),row[0],new)


def upgrade(config,confirm=None):
    plan=preview(config)
    if confirm is None:return dict(plan,applied=False)
    if confirm!=plan['plan_sha256']:raise ValueError('预演已变化，请重新预演确认')
    if not plan['changes']:return dict(plan,applied=False,backup=None)
    from app.storage.maintenance import backup
    saved=backup(config.data,config.root)
    if any(e['store']=='library' for e in plan['changes']):
        from app.storage.library_backup import backup_library
        saved['library_backup']=backup_library(config.library_dir,workspaces=[config.data])
    # Revalidate all file bytes and rows after backup, before any write.
    if preview(config)['plan_sha256']!=confirm:raise ValueError('备份期间数据已变化，请重新预演')
    for owner,db in stores(config).items():
        selected=[e for e in plan['changes'] if e['store']==owner]
        if not selected:continue
        with closing(sqlite3.connect(db)) as conn,conn:
            conn.execute('BEGIN IMMEDIATE')
            for e in selected:
                if owner=='session':
                    conversion=_session_change(config)
                    if not conversion or conversion[0]!=e:raise ValueError('会话投影已变化')
                    conn.execute('UPDATE session SET payload=? WHERE id=1 AND payload=?',(conversion[2],conversion[1]))
                    continue
                cursor=conn.execute('UPDATE '+e['table']+' SET '+e['field']+'=? WHERE '+e['key']+'=? AND '+e['field']+'=?',
                    (e['relative'],e['id'],e['old']))
                if cursor.rowcount!=1:raise ValueError('待迁移记录已变化')
    for e in plan['changes']:
        if e['store']=='config':
            marker=config.data/'workspace.json';value=json.loads(marker.read_text(encoding='utf8'))
            value['library']=e['relative']
            staged=marker.with_suffix('.json.tmp');staged.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');staged.replace(marker)
    return dict(plan,applied=True,backup=saved)


def status(config):
    from app.config import library_env_override
    # Settings must never parse mathematical/history JSON or hash file content.
    invalid=[];legacy=[]
    for owner,db in stores(config).items():
        if not db.is_file() or not FIELDS[owner]:continue
        root=config.library_dir if owner=='library' else config.data
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as conn:
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table,key,field,_ in FIELDS[owner]:
                if table not in tables:continue
                for identity,value in conn.execute('SELECT '+key+','+field+' FROM '+table+' WHERE '+field+" IS NOT NULL AND "+field+"!=''"):
                    text=str(value).replace('\\','/')
                    old=bool(ntpath.splitdrive(text)[0] or text.startswith('/') or '..' in text.split('/'))
                    # Existence only; strict symlink resolution and hashes belong
                    # to preview/access, not to the settings read model.
                    exists=not old and os.path.isfile(os.path.join(root,text))
                    item=dict(store=owner,table=table,key=key,id=identity,field=field,old=value,
                        relative=None if old else text,exists=exists,sha256=None,expected_sha256=None,
                        change=old,valid_location=exists,verified=None,can_migrate=False)
                    if not exists:invalid.append(item)
                    if old:legacy.append(item)
    from app.config import library_location
    marker=config.data/'workspace.json'
    config_pending=False
    if marker.is_file():
        value=json.loads(marker.read_text(encoding='utf8')).get('library','')
        config_pending=Path(value).is_absolute() and Path(value)!=Path(library_location(config.data,config.library_dir))
    count=len(legacy)+int(config_pending)
    backups=list((config.data/'backups').glob('*.zip'))
    return dict(data_dir=str(config.data),library_dir=str(config.library_dir),
        library_exists=config.library_dir.is_dir(),library_env_override=library_env_override(config.data),
        databases={k:dict(bytes=p.stat().st_size if p.is_file() else 0,exists=p.is_file()) for k,p in stores(config).items()},
        invalid_file_references=dict(count=len(invalid),examples=invalid[:10]),
        last_backup_at=datetime.fromtimestamp(max(p.stat().st_mtime for p in backups),timezone.utc).isoformat() if backups else None,
        backup_retention_count=3,
        path_migration=dict(pending=bool(count),ready_count=0,
            unresolved_count=count,historical_reference_count=0,plan_sha256=digest([legacy,config_pending])))
