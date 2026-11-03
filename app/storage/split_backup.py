"""Personal workspace backup; the shared library is identified, not bundled."""
from pathlib import Path
import tempfile

from app.storage.boundaries import workspace_config
from app.storage.backup_archive import PERSONAL, publish, snapshot, file_sha256


def library_identity(library, staging):
    source=Path(library)/'library.db'
    if not source.is_file():raise ValueError('library_missing：通用库不存在，请先恢复备份清单所需题库')
    target=Path(staging)/'library-identity.db'
    snapshot(source,target)
    return dict(scheme='sqlite-backup-sha256/v1',sha256=file_sha256(target),location=str(Path(library).resolve()))


def backup(data, root):
    config=workspace_config(data,root)
    folder=data/'backups';folder.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        staging=Path(temp)
        identity=library_identity(config.library_dir,staging)
        databases={config.database.name:config.database}
        if (data/'agent-session.db').exists():databases['agent-session.db']=data/'agent-session.db'
        for name,source in databases.items():
            snapshot(source,staging/name)
        files={}
        for source in data.rglob('*'):
            if (not source.is_file() or source.is_symlink() or source.is_relative_to(folder)
                    or source.is_relative_to(config.library_dir) or source.is_relative_to(data/'trash')
                    or source.name.endswith(('-journal','-wal','-shm','.log'))):continue
            name=source.relative_to(data).as_posix()
            files[name]=staging/name if name in databases else source
        manifest=dict(kind='workspace',data_root=str(data),project_root=str(root),
                      workspace_database=config.database.name,library=identity)
        return publish(folder,'mathlens-personal',PERSONAL,manifest,files,keep=3)
