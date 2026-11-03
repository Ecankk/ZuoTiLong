"""Explicit per-application paths; constructing settings never creates data."""
from dataclasses import dataclass
from pathlib import Path
import os
import json


def library_env_override(data):
    selected=os.environ.get('MATHLENS_DATA_DIR')
    return bool(selected and Path(data).resolve()==Path(selected).resolve() and 'MATHLENS_LIBRARY_DIR' in os.environ)


def library_location(data, library):
    """Only the library root locator may cross volumes or contain parents."""
    data,library=Path(data).resolve(),Path(library).resolve()
    if data.drive.casefold()!=library.drive.casefold():return library.as_posix()
    return Path(os.path.relpath(library,data)).as_posix()


def resolve_library_dir(data, default):
    """Scope the environment's library override to its selected workspace."""
    if library_env_override(data):
        default = os.environ['MATHLENS_LIBRARY_DIR']
    candidate=Path(default)
    return (candidate if candidate.is_absolute() else Path(data)/candidate).resolve()


@dataclass(frozen=True)
class AppConfig:
    root: Path
    data: Path
    dist: Path
    database: Path
    demo: bool = False
    library: Path | None = None

    @property
    def library_dir(self) -> Path:
        return self.library or self.data / 'library'

    @property
    def library_database(self) -> Path:
        return self.library_dir / 'library.db'

    @property
    def papers(self) -> Path:
        return self.data / 'papers'

    @classmethod
    def from_env(cls, root=None):
        root = Path(root or Path(__file__).resolve().parents[1]).resolve()
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share')) / 'ZuoTiLong'
        data = Path(os.environ.get('MATHLENS_DATA_DIR', base / 'workspaces' / 'default')).resolve()
        default_library = data / 'library' if os.environ.get('MATHLENS_DATA_DIR') else base / 'library'
        location = json.loads((data/'workspace.json').read_text(encoding='utf8')) if (data/'workspace.json').is_file() else {}
        library = resolve_library_dir(data, location.get('library',default_library))
        database_name = location.get('database','learning.db')
        if Path(database_name).name != database_name:
            raise ValueError('Invalid workspace database name')
        database = data / database_name
        dist = Path(os.environ.get('MATHLENS_DIST_DIR', root / 'dist')).resolve()
        return cls(root, data, dist, database, os.environ.get('MATHLENS_DEMO') == '1', library)
