"""An explicit two-store backup; the original library is never a restore target."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid
import zipfile

from app.storage.boundaries import workspace_config


def backup(data, root):
    config=workspace_config(data,root)
    folder=data/'backups';folder.mkdir(exist_ok=True)
    target=folder/('mathlens-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.zip')
    manifest={'format':2,'data_root':str(data),'project_root':str(root),
              'workspace_database':config.database.name,'sha256':{}}
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        staging=Path(temp)
        databases={config.database.name:config.database,'__library__/library.db':config.library_database}
        if (data/'agent-session.db').exists():databases['agent-session.db']=data/'agent-session.db'
        for name,source in databases.items():
            actual=staging/name;actual.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as old,closing(sqlite3.connect(actual)) as new:
                old.backup(new)
        files={}
        for source in data.rglob('*'):
            if (not source.is_file() or source.is_symlink() or source.is_relative_to(folder)
                    or source.is_relative_to(config.library_dir) or source.is_relative_to(data/'trash')
                    or source.name.endswith(('-journal','-wal','-shm','.log'))):continue
            name=source.relative_to(data).as_posix()
            files[name]=staging/name if name in databases else source
        for directory in ('bank-assets','knowledge-sources'):
            for source in (config.library_dir/directory).rglob('*'):
                if source.is_file() and not source.is_symlink():
                    files['__library__/'+source.relative_to(config.library_dir).as_posix()]=source
        files['__library__/library.db']=staging/'__library__/library.db'
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,source in files.items():
                raw=source.read_bytes();archive.writestr(name,raw)
                manifest['sha256'][name]=hashlib.sha256(raw).hexdigest()
            archive.writestr('backup-manifest.json',json.dumps(manifest,ensure_ascii=False))
    return {'path':str(target),'files':len(files)}
