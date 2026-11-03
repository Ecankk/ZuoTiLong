"""Explicit shared-library maintenance, independent of the personal backup UI."""
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile

from app.storage.backup_archive import LIBRARY, publish, validate, extract
from app.storage.boundaries import workspace_config
from app.storage.split_backup import library_identity


@contextmanager
def maintenance_guard(library, workspaces=()):
    library=Path(library).resolve()
    selected=[library.parent,*workspaces,*((library.parent/'workspaces').glob('*'))]
    if os.environ.get('MATHLENS_DATA_DIR'):selected.append(Path(os.environ['MATHLENS_DATA_DIR']))
    for data in {Path(p).resolve() for p in selected}:
        if not (data/'workspace.json').is_file():continue
        config=workspace_config(data)
        if config.library_dir != library:continue
        session=data/'agent-session.db'
        if session.is_file():
            with closing(sqlite3.connect(session.as_uri()+'?mode=ro',uri=True)) as conn:
                row=conn.execute('SELECT payload FROM session WHERE id=1').fetchone()
            state=json.loads(row[0]) if row else {}
            if state.get('active_request') or state.get('external_control') or state.get('status')=='connecting':
                raise ValueError('学习任务/外部会话正在使用通用库，请先结束或释放后再备份')
        if config.database.is_file():
            with closing(sqlite3.connect(config.database.as_uri()+'?mode=ro',uri=True)) as conn:
                tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table,statuses in (('workflow_jobs',"'queued','dispatching','running'"),
                                       ('learning_tasks',"'queued','running','repairing','result_saved'")):
                    if table in tables and conn.execute('SELECT 1 FROM '+table+' WHERE status IN ('+statuses+') LIMIT 1').fetchone():
                        raise ValueError('工作区仍有待执行或未完成学习任务，请先完成或取消后再备份通用库')
    path=library/'library.db'
    if not path.is_file():raise ValueError('library_missing：指定通用库不存在')
    with closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=0)) as guard:
        try:guard.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as exc:
            if getattr(exc,'sqlite_errorcode',None) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                raise ValueError('通用库正在写入，请稍后重试备份') from exc
            raise
        try:yield
        finally:guard.rollback()


def backup_library(library, *, workspaces=()):
    library=Path(library).resolve()
    with maintenance_guard(library,workspaces):
        folder=library.parent/'backups';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            staging=Path(temporary)
            identity=library_identity(library,staging)
            files={'library.db':staging/'library-identity.db'}
            for directory in ('bank-assets','knowledge-sources'):
                for source in (library/directory).rglob('*'):
                    if source.is_file() and not source.is_symlink() and source.resolve().is_relative_to(library):
                        files[source.relative_to(library).as_posix()]=source
            return publish(folder,'mathlens-library',LIBRARY,dict(kind='library',library=identity),files,keep=5)


def restore_library(archive_path, destination):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('题库恢复目录必须不存在，不能覆盖当前通用库')
    with zipfile.ZipFile(archive_path) as archive:
        manifest=validate(archive,formats=(3,))
        if (manifest.get('producer')!=LIBRARY or manifest.get('kind')!='library'
                or manifest.get('library',{}).get('sha256')!=manifest['sha256'].get('library.db')
                or any(name!='library.db' and not name.startswith(('bank-assets/','knowledge-sources/')) for name in manifest['sha256'])):
            raise ValueError('不是完整的通用库备份')
        destination.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            staged=Path(temporary)/'library';staged.mkdir()
            extract(archive,staged,manifest)
            with closing(sqlite3.connect((staged/'library.db').as_uri()+'?mode=ro',uri=True)) as conn:
                if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('题库数据库完整性校验失败')
            staged.rename(destination)
    return dict(restored_to=str(destination),files=len(manifest['sha256']),library=dict(manifest['library'],location=str(destination)))
