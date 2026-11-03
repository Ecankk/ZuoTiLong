"""Verified ZIP publication and rotation for explicitly owned backups."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid
import zipfile

PERSONAL = 'mathlens.personal-backup/v1'
LIBRARY = 'mathlens.library-backup/v1'


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):digest.update(block)
    return digest.hexdigest()


def snapshot(source, target):
    with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro', uri=True)) as old, \
         closing(sqlite3.connect(target)) as new:
        old.backup(new)
        if new.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('数据库备份完整性校验失败')


def validate(archive, *, formats=(1, 2, 3)):
    entries = archive.infolist()
    if len(entries)>30000 or sum(e.file_size for e in entries)>8*1024**3:raise ValueError('备份包过大')
    names = [e.filename for e in entries]
    if len(set(names)) != len(names):raise ValueError('备份包含重复文件')
    for entry in entries:
        path = Path(entry.filename)
        if (not entry.filename or '\\' in entry.filename or ':' in entry.filename or path.is_absolute()
                or '..' in path.parts or entry.is_dir()
                or (entry.external_attr>>16)&0o170000 == 0o120000):
            raise ValueError('备份路径不合法')
    manifest = json.loads(archive.read('backup-manifest.json'))
    if (not isinstance(manifest,dict) or manifest.get('format') not in formats or not isinstance(manifest.get('sha256'),dict)
            or set(names) != {*manifest['sha256'], 'backup-manifest.json'}):
        raise ValueError('备份清单不完整')
    for name, expected in manifest['sha256'].items():
        digest = hashlib.sha256()
        with archive.open(name) as source:
            for block in iter(lambda: source.read(1024*1024), b''):digest.update(block)
        if digest.hexdigest() != expected:raise ValueError('备份文件校验失败：'+name)
    return manifest


def extract(archive, destination, manifest):
    for name in manifest['sha256']:
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True)
        with archive.open(name) as source, path.open('xb') as target:
            for block in iter(lambda: source.read(1024*1024), b''):target.write(block)


def _rotate(folder, target, prefix, producer, keep):
    pattern = re.compile(re.escape(prefix)+r'-\d{8}-\d{6}-[0-9a-f]{12}\.zip')
    owned = []
    for path in folder.iterdir():
        if path == target or path.is_symlink() or not path.is_file() or not pattern.fullmatch(path.name):continue
        try:
            with zipfile.ZipFile(path) as archive:
                marker=json.loads(archive.read('backup-manifest.json'))
            if isinstance(marker,dict) and marker.get('format') == 3 and marker.get('producer') == producer:
                owned.append(path)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            # An unrecognized file is not ours to delete.
            continue
    removed=[]
    for path in sorted(owned,key=lambda p:(p.stat().st_mtime_ns,p.name),reverse=True)[keep-1:]:
        path.unlink();removed.append(path.name)
    return removed


def publish(folder, prefix, producer, manifest, files, *, keep):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    target=folder/(prefix+'-'+stamp+'-'+uuid.uuid4().hex[:12]+'.zip')
    partial=folder/('.'+target.name+'.partial')
    manifest={**manifest,'format':3,'producer':producer,'created_at':datetime.now(timezone.utc).isoformat(),'sha256':{}}
    try:
        with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,path in files.items():
                digest=hashlib.sha256()
                with Path(path).open('rb') as source, archive.open(name,'w') as output:
                    for block in iter(lambda:source.read(1024*1024),b''):
                        output.write(block);digest.update(block)
                manifest['sha256'][name]=digest.hexdigest()
            archive.writestr('backup-manifest.json',json.dumps(manifest,ensure_ascii=False))
        with zipfile.ZipFile(partial) as archive:validate(archive,formats=(3,))
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    # Never delete a previous backup before the replacement has been verified.
    removed=_rotate(folder,target,prefix,producer,keep)
    return dict(path=str(target),files=len(files),retention_count=keep,removed=removed)
