"""Copy a release seed into a user-owned library; publish only verified bytes."""
from contextlib import closing,contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time

from app.desktop.control import checkpoint
from app.desktop.protocol import DesktopError
from app.storage.paths import resolve_file
from app.version import VERSION


@contextmanager
def prepare_lock(parent):
    parent.mkdir(parents=True,exist_ok=True)
    lock_path=parent/'.mathlens-prepare.lock';stream=lock_path.open('a+b')
    acquired=False
    try:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise DesktopError('library_busy','另一个进程正在准备题库',13) from None
        acquired=True
        yield
    finally:
        if acquired:
            try:
                stream.seek(0)
                if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(stream,fcntl.LOCK_UN)
            finally:
                stream.close()
                try:lock_path.unlink()
                except FileNotFoundError:pass
        else:stream.close()


def manifest(root):
    try:
        value=json.loads((root/'manifest.json').read_text(encoding='utf8'))
        if set(value)!={'schema','release_id','min_app_version','library_id','library_revision','counts','collections','files'}:raise ValueError()
        if value['schema']!='mathlens.library-seed/v1' or any(not isinstance(value[k],str) or not value[k] for k in ('release_id','library_id')):raise ValueError()
        version=lambda s:tuple(map(int,s.split('.'))) if re.fullmatch(r'\d+\.\d+\.\d+',s) else ()
        if not version(value['min_app_version']):raise ValueError()
        if version(value['min_app_version'])>version(VERSION):raise DesktopError('seed_incompatible','题库需要较新的应用版本',11)
        if type(value['library_revision']) is not int or value['library_revision']<0:raise ValueError()
        counts=value['counts']
        if set(counts)!={'questions','ready'} or any(type(n) is not int or n<0 for n in counts.values()) or counts['ready']>counts['questions']:raise ValueError()
        if not isinstance(value['collections'],list) or len({c['id'] for c in value['collections']})!=len(value['collections']):raise ValueError()
        for c in value['collections']:
            if set(c)!={'id','total','ready'} or not isinstance(c['id'],str) or not c['id'] or any(type(c[k]) is not int or c[k]<0 for k in ('total','ready')) or c['ready']>c['total']:raise ValueError()
        files=value['files'];seen=set()
        if not isinstance(files,dict) or 'library.db' not in files:raise ValueError()
        for name,item in files.items():
            if not isinstance(name,str) or '\\' in name or name.casefold() in seen or name!='library.db' and not name.startswith(('bank-assets/','knowledge-sources/')):raise ValueError()
            seen.add(name.casefold());resolve_file(root,name)
            if set(item)!={'sha256','size'} or not re.fullmatch('[a-f0-9]{64}',item['sha256']) or type(item['size']) is not int or item['size']<0:raise ValueError()
        actual=set()
        for p in root.rglob('*'):
            checkpoint()
            if p.is_symlink() or getattr(p,'is_junction',lambda:False)() or not p.resolve().is_relative_to(root.resolve()):raise ValueError()
            if p.is_file():actual.add(p.relative_to(root).as_posix())
        if actual!=set(files)|{'manifest.json'}:raise ValueError()
        return value
    except (KeyError,ValueError,TypeError,OSError):raise DesktopError('seed_invalid','题库清单或文件集合不合法',11) from None


def verify_files(root,value,protocol):
    total=sum(x['size'] for x in value['files'].values());done=0;last=0
    for name,item in value['files'].items():
        checkpoint();path=resolve_file(root,name)
        if not path.is_file() or path.stat().st_size!=item['size']:raise DesktopError('seed_hash_mismatch','题库文件大小不符',11)
        sha=hashlib.sha256()
        with path.open('rb') as stream:
            while data:=stream.read(1024*1024):
                checkpoint();sha.update(data);done+=len(data)
                if time.monotonic()-last>.2:
                    protocol.progress(protocol.phase,'正在校验本地题库',progress=dict(unit='bytes',completed=done,total=total));last=time.monotonic()
        if sha.hexdigest()!=item['sha256']:raise DesktopError('seed_hash_mismatch','题库文件散列不符',11)


def validate_database(root,value=None):
    try:return _validate_database(root,value)
    except (sqlite3.Error,ValueError,KeyError,TypeError) as exc:
        checkpoint()
        if getattr(exc,'sqlite_errorcode',None) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):raise DesktopError('library_busy','题库正在由其他进程使用',13) from exc
        raise DesktopError('seed_db_invalid','题库数据库或资源引用不合法',11) from exc


def _validate_database(root,value):
    from app.storage.boundaries import LIBRARY_TABLES
    with closing(sqlite3.connect((root/'library.db').as_uri()+'?mode=ro',uri=True)) as conn:
        from app.desktop.control import CANCEL
        stop=CANCEL.get()
        if stop is not None:conn.set_progress_handler(lambda:int(stop.is_set()),10000)
        checkpoint()
        if conn.execute('PRAGMA integrity_check').fetchall()!=[('ok',)] or conn.execute('PRAGMA foreign_key_check').fetchone():raise DesktopError('seed_db_invalid','题库数据库完整性检查失败',11)
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'bank_questions','bank_resources','library_state','bank_collections'}<=tables or tables-LIBRARY_TABLES:raise DesktopError('seed_db_invalid','题库数据库结构不合法',11)
        identity=conn.execute('SELECT library_id,revision FROM library_state WHERE singleton=1').fetchone()
        if not identity:raise DesktopError('seed_db_invalid','题库标识缺失',11)
        if value and (identity[0],identity[1])!=(value['library_id'],value['library_revision']):raise DesktopError('seed_db_invalid','题库标识与发行清单不符',11)
        for row in conn.execute('SELECT question_path,answer_path,analysis_path FROM bank_resources'):
            checkpoint()
            for name in row:
                if not name:continue
                p=resolve_file(root,name)
                if not p.is_file() or value and p.relative_to(root).as_posix() not in value['files']:raise DesktopError('seed_db_invalid','题库资源引用缺失',11)
        if 'knowledge_source_entries' in tables:
            for version,payload in conn.execute('SELECT source_version_id,payload_json FROM knowledge_source_entries'):
                entry=json.loads(payload)
                for ref in entry.get('references',entry.get('record',{}).get('references',[])):
                    checkpoint();relative='knowledge-sources/'+version+'/'+ref['path'];p=resolve_file(root,relative)
                    if not p.is_file() or value and (relative not in value['files'] or value['files'][relative]['sha256']!=ref['sha256']):raise DesktopError('seed_db_invalid','目录来源材料缺失或散列不符',11)
        if value:
            if conn.execute('SELECT count(*) FROM bank_questions').fetchone()[0]!=value['counts']['questions']:raise DesktopError('seed_db_invalid','题库题数不符',11)
            actual=dict(conn.execute('SELECT collection_id,count(*) FROM bank_questions GROUP BY collection_id'))
            if {c['id']:c['total'] for c in value['collections'] if c['total']}!=actual:raise DesktopError('seed_db_invalid','题集题数不符',11)
            # Count the latest published annotation per source question. The
            # release builder verifies mathematical/material/definition trust;
            # startup does not repeat every annotation proof or solve questions.
            latest={}
            if {'question_annotation_links','question_annotations','prepared_annotation_ids'}<=tables:
                for bid,status,order in conn.execute('''SELECT l.bank_id,json_extract(a.payload_json,'$.status'),p.rowid
                    FROM question_annotation_links l JOIN question_annotations a ON a.id=l.annotation_id
                    JOIN prepared_annotation_ids p ON p.id=a.id'''):
                    if bid not in latest or latest[bid][0]<order:latest[bid]=(order,status)
            if {'imported_question_annotations','annotation_cache_state','prepared_annotation_ids'}<=tables:
                for bid,order in conn.execute('''SELECT a.bank_id,p.rowid FROM imported_question_annotations a
                    JOIN annotation_cache_state s ON s.package_sha256=a.package_sha256 AND s.enabled=1
                    JOIN prepared_annotation_ids p ON p.id=a.id'''):
                    if bid not in latest or latest[bid][0]<order:latest[bid]=(order,'ready')
            ready={bid for bid,(_,status) in latest.items() if status=='ready'}
            counts={}
            for bid,group in conn.execute('SELECT id,collection_id FROM bank_questions'):
                if bid in ready:counts[group]=counts.get(group,0)+1
            if len(ready)!=value['counts']['ready'] or any(counts.get(c['id'],0)!=c['ready'] for c in value['collections']):raise DesktopError('seed_db_invalid','题库标注计数不符',11)
        return identity[0]


def check_workspace(config):
    if (config.data/'workspace.json').is_file():return
    if config.database.exists():
        if (config.data/'agent-session.db').exists() or any(p.is_dir() and any(p.iterdir()) for p in config.data.iterdir()):
            raise DesktopError('workspace_incomplete','已有会话或个人材料但缺少定位配置，请重新定位或恢复',12)
        from app.storage.boundaries import LIBRARY_TABLES
        with closing(sqlite3.connect(config.database.as_uri()+'?mode=ro',uri=True)) as conn:
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            from app.storage.split import template
            with closing(template()) as schema:allowed={r[0] for r in schema.execute("SELECT name FROM sqlite_master WHERE type='table'")}-LIBRARY_TABLES
            if tables-allowed:raise DesktopError('workspace_incomplete','缺少工作区定位配置，请重新定位或恢复',12)
            for table in tables-{'preferences','tool_audit'}:
                if conn.execute('SELECT 1 FROM "'+table+'" LIMIT 1').fetchone():raise DesktopError('workspace_incomplete','已有个人记录但缺少定位配置，请重新定位或恢复',12)
    elif config.data.exists() and any(config.data.iterdir()):
        raise DesktopError('workspace_incomplete','所选工作区并非空目录，请重新定位',12)


def prepare(config,protocol):
    published=False;staging=None;value=None;reused=False
    try:
        protocol.progress('inspect_existing','正在检查已有本地题库');checkpoint();check_workspace(config)
        with prepare_lock(config.library_dir.parent):
            if config.library_database.is_file():
                library_id=validate_database(config.library_dir);reused=True;published=True
            else:
                if config.library_dir.exists() and any(config.library_dir.iterdir()):raise DesktopError('library_incomplete','题库目录不完整，请重新定位或恢复',12)
                protocol.progress('validate_seed','正在检查发行题库');seed=config.root/'library-seed';value=manifest(seed)
                required=sum(x['size'] for x in value['files'].values())+16*1024*1024
                if shutil.disk_usage(config.library_dir.parent).free<required:raise DesktopError('disk_full','题库所在磁盘空间不足',10)
                verify_files(seed,value,protocol)
                staging=Path(tempfile.mkdtemp(prefix='library.staging-',dir=config.library_dir.parent))
                protocol.progress('copy_seed','正在准备本地题库');total=sum(x['size'] for x in value['files'].values());done=0;last=0
                for name in value['files']:
                    checkpoint();target=resolve_file(staging,name);target.parent.mkdir(parents=True,exist_ok=True)
                    with resolve_file(seed,name).open('rb') as source,target.open('xb') as output:
                        while chunk:=source.read(1024*1024):
                            checkpoint();output.write(chunk);done+=len(chunk)
                            if time.monotonic()-last>.2:
                                protocol.progress('copy_seed','正在准备本地题库',progress=dict(unit='bytes',completed=done,total=total));last=time.monotonic()
                protocol.progress('verify_seed','正在校验复制的题库');verify_files(staging,value,protocol);library_id=validate_database(staging,value)
                checkpoint();protocol.progress('publish_library','正在保存已校验的题库')
                if config.library_dir.exists():config.library_dir.rmdir()  # Only empty, never recursive.
                staging.rename(config.library_dir);published=True
            checkpoint();protocol.progress('initialize_workspace','正在准备个人工作区')
            config.data.parent.mkdir(parents=True,exist_ok=True)
            parent=config.data if config.data.is_dir() else config.data.parent
            if shutil.disk_usage(parent).free<16*1024*1024:raise DesktopError('disk_full','工作区所在磁盘空间不足',10)
            with tempfile.TemporaryFile(dir=parent) as probe:probe.write(b'workspace writable');probe.flush()
            from app.storage.database import Database
            Database(config).initialize();checkpoint();protocol.phase='complete'
            result=dict(reused_library=reused,library_published=True,workspace_ready=True,data_dir=str(config.data),library_dir=str(config.library_dir),library_id=library_id,seed_release_id=value['release_id'] if value else None)
            protocol.emit('prepared',status='completed',**result);return result
    except Exception as exc:
        exc.library_published=published;exc.workspace_ready=False
        raise
    finally:
        if staging and staging.exists():
            if staging.resolve().parent!=config.library_dir.parent.resolve() or not staging.name.startswith('library.staging-'):raise RuntimeError('Invalid owned staging path')
            shutil.rmtree(staging)
