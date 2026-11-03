"""Personal workspace backup; the shared library is identified, not bundled."""
from pathlib import Path
import tempfile

from app.storage.boundaries import workspace_config
from app.storage.backup_archive import PERSONAL, publish, snapshot
from app.storage.library_identity import read as library_identity


def backup(data, root):
    config=workspace_config(data,root)
    folder=data/'backups';folder.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        staging=Path(temp)
        identity=library_identity(config.library_dir)
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
