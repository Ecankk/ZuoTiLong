"""Recoverable local maintenance. Never overwrite an existing restore target."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
import uuid
import zipfile


def backup(data,root):
    folder=data/'backups';folder.mkdir(exist_ok=True)
    target=folder/('mathlens-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.zip')
    staging=folder/('snapshot-'+uuid.uuid4().hex);staging.mkdir()
    try:
        for name in ('mathlens.db','agent-session.db'):
            source=data/name
            if source.is_file():
                with closing(sqlite3.connect(source)) as src,closing(sqlite3.connect(staging/name)) as dst:src.backup(dst)
        manifest={'format':1,'data_root':str(data),'project_root':str(root),'sha256':{}}
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
            files=[p for p in data.rglob('*') if p.is_file() and not p.is_symlink() and not p.is_relative_to(folder) and not p.is_relative_to(data/'trash') and not any(part.startswith('restore-') for part in p.relative_to(data).parts) and p.suffix not in ('.log',) and not p.name.endswith(('-wal','-shm','.pid'))]
            for source in files:
                relative=source.relative_to(data).as_posix();actual=staging/source.name if source.parent==data and (staging/source.name).is_file() else source
                raw=actual.read_bytes();archive.writestr(relative,raw);manifest['sha256'][relative]=hashlib.sha256(raw).hexdigest()
            archive.writestr('backup-manifest.json',json.dumps(manifest,ensure_ascii=False))
        return {'path':str(target),'files':len(manifest['sha256'])}
    finally:
        if staging.resolve().parent==folder.resolve():shutil.rmtree(staging)


def restore(archive_path,destination):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('恢复目录必须不存在，不能覆盖当前个人资料')
    with zipfile.ZipFile(archive_path) as archive:
        entries=archive.infolist()
        if len(entries)>30000 or sum(e.file_size for e in entries)>8*1024**3:raise ValueError('备份包过大')
        names=[e.filename for e in entries]
        if len(set(names))!=len(names):raise ValueError('备份包含重复文件')
        for entry in entries:
            path=(destination/entry.filename).resolve()
            if '\\' in entry.filename or ':' in entry.filename or not path.is_relative_to(destination) or (entry.external_attr>>16)&0o170000==0o120000:raise ValueError('备份路径不合法')
        manifest=json.loads(archive.read('backup-manifest.json'))
        if manifest.get('format')!=1 or set(names)!={*manifest['sha256'],'backup-manifest.json'}:raise ValueError('备份清单不完整')
        # Validate every checksum before creating the destination.
        for name,digest in manifest['sha256'].items():
            if hashlib.sha256(archive.read(name)).hexdigest()!=digest:raise ValueError('备份文件校验失败：'+name)
        destination.mkdir(parents=True)
        for name in manifest['sha256']:
            path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(name))
    old_data=Path(manifest['data_root']);old_root=Path(manifest['project_root'])
    with closing(sqlite3.connect(destination/'mathlens.db')) as conn,conn:
        for pid,relative in conn.execute('SELECT id,source_path FROM papers WHERE source_path IS NOT NULL'):
            old=(old_root/relative).resolve()
            if old.is_relative_to(old_data.resolve()):conn.execute('UPDATE papers SET source_path=? WHERE id=?',(str(destination/old.relative_to(old_data.resolve())),pid))
    for path in (destination/'tasks').glob('*/request.json'):
        text=path.read_text(encoding='utf8').replace(json.dumps(str(old_data))[1:-1],json.dumps(str(destination))[1:-1]);path.write_text(text,encoding='utf8')
    return {'restored_to':str(destination),'files':len(manifest['sha256'])}


def cleanup_images(conn,data,min_age=86400):
    references=set()
    for row in conn.execute('SELECT images_json FROM probe_attempts'):references.update(json.loads(row[0]))
    session=data/'agent-session.db'
    if session.is_file():
        with closing(sqlite3.connect(session)) as db:
            row=db.execute('SELECT payload FROM session WHERE id=1').fetchone()
        for turn in json.loads(row[0]).get('turns',[]) if row else []:references.update(turn.get('image_ids',[]))
    for path in (data/'drafts').glob('*.json'):
        raw=path.read_text(encoding='utf8')
        import re
        references.update(re.findall(r'image-[0-9a-f]{32}',raw))
    moved=0;trash=data/'trash'/('unused-uploads-'+uuid.uuid4().hex)
    for folder in (data/'answer-images').glob('image-*'):
        if folder.name in references or time.time()-folder.stat().st_mtime<min_age:continue
        if folder.resolve().parent!=(data/'answer-images').resolve() or folder.is_symlink():continue
        trash.mkdir(parents=True,exist_ok=True);shutil.move(str(folder),str(trash/folder.name));conn.execute('DELETE FROM answer_images WHERE id=?',(folder.name,));moved+=1
    return {'moved':moved,'recoverable_directory':str(trash) if moved else None}
