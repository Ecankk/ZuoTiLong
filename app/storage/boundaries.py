"""Physical ownership of shared mathematics and private learning records."""
import json
from pathlib import Path
import re
import sqlite3
from app.config import resolve_library_dir

LIBRARY_TABLES = frozenset('''
bank_questions bank_resources bank_identity bank_links bank_identity_reviews
bank_metadata_revisions question_annotations question_annotation_links
question_annotation_topics prepared_annotation_ids imported_question_annotations
imported_annotation_topics annotation_cache_packages annotation_cache_state
annotation_cache_imports knowledge_nodes knowledge_source_versions
knowledge_source_entries knowledge_catalog_releases knowledge_catalog_state
knowledge_catalog_nodes knowledge_catalog_redirects knowledge_catalog_packages
knowledge_package_sources knowledge_package_entries knowledge_package_activations
annotation_provenance
'''.split())


def schema_rows(conn, kind='table'):
    values = list(conn.execute('SELECT * FROM main.sqlite_master WHERE type=?', (kind,)))
    if any(r[1] == 'library' for r in conn.execute('PRAGMA database_list')):
        values += list(conn.execute('SELECT * FROM library.sqlite_master WHERE type=?', (kind,)))
    return values


def table_exists(conn, name):
    return any(row['name'] == name for row in schema_rows(conn))


def scoped_schema(sql, table):
    """SQLite FKs are local to a file; cross-domain IDs are checked by services."""
    owner = table in LIBRARY_TABLES
    def reference(match):
        return match[0] if (match[1] in LIBRARY_TABLES) == owner else ''
    return re.sub(r'REFERENCES\s+(\w+)\s*\([^)]*\)(?:\s+ON\s+DELETE\s+(?:SET NULL|CASCADE|RESTRICT|NO ACTION))?',
                  reference, sql, flags=re.I)


def save_location(config):
    if config.database.resolve().parent != config.data.resolve():
        raise ValueError('The learning database must belong to this workspace')
    value = {'database': config.database.name, 'library': str(config.library_dir.resolve())}
    path = config.data / 'workspace.json'
    raw = json.dumps(value, ensure_ascii=False)
    if not path.exists() or path.read_text(encoding='utf8') != raw:
        path.write_text(raw, encoding='utf8')


def workspace_config(data, root=None):
    from app.config import AppConfig
    data = Path(data).resolve()
    path = data / 'workspace.json'
    if path.exists():
        value = json.loads(path.read_text(encoding='utf8'))
        if Path(value['database']).name != value['database']:
            raise ValueError('Invalid workspace database name')
        return AppConfig(Path(root or Path(__file__).resolve().parents[2]), data,
                         Path(root or '.') / 'dist', data/value['database'], library=resolve_library_dir(data,value['library']))
    return AppConfig(Path(root or '.'), data, Path(root or '.') / 'dist', data / 'mathlens.db',
                     library=resolve_library_dir(data,data/'library'))


def library_root(data):
    marker = Path(data) / 'workspace.json'
    return resolve_library_dir(data,json.loads(marker.read_text(encoding='utf8'))['library'] if marker.exists() else data)


def material_path(data, relative):
    relative = Path(relative)
    root = library_root(data) if relative.parts and relative.parts[0] in ('bank-assets', 'knowledge-sources') else Path(data)
    return root / relative


def connect_workspace(config, *, library_write=False, readonly=False):
    config.data.mkdir(parents=True, exist_ok=True)
    path = config.database.resolve().as_uri() + ('?mode=ro' if readonly else '?mode=rwc')
    conn = sqlite3.connect(path, timeout=15, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        uri = config.library_database.resolve().as_uri() + ('?mode=rw' if library_write else '?mode=ro')
        conn.execute('ATTACH DATABASE ? AS library', (uri,))
        conn.execute('PRAGMA foreign_keys=ON')
        return conn
    except BaseException:
        conn.close()
        raise


def enable_library_writes(conn, config):
    if any(r[1]=='library' for r in conn.execute('PRAGMA database_list')):
        conn.execute('DETACH DATABASE library')
        conn.execute('ATTACH DATABASE ? AS library', (config.library_database.resolve().as_uri()+'?mode=rw',))
