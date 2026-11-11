"""Create two stores and move a legacy installation without modifying it."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from types import SimpleNamespace

from app.storage.boundaries import LIBRARY_TABLES, save_location, scoped_schema


def template():
    from app.storage.database import _initialize_connection
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    _initialize_connection(SimpleNamespace(config=SimpleNamespace(demo=False)), conn)
    conn.execute('''CREATE TABLE annotation_provenance(
        annotation_id TEXT PRIMARY KEY REFERENCES question_annotations(id),
        payload_json TEXT NOT NULL)''')
    conn.execute('CREATE TABLE IF NOT EXISTS tool_audit(id INTEGER PRIMARY KEY,action TEXT,record_id TEXT,created_at TEXT)')
    from app.storage.library_identity import initialize
    initialize(conn)
    conn.commit()
    return conn


def copy_schema(source, target, names):
    for row in source.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY rowid"):
        if row['name'] in names:
            target.execute(scoped_schema(row['sql'].replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ', 1), row['name']))
    for row in source.execute("SELECT tbl_name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL AND name!='idx_bank_collection'"):
        if row['tbl_name'] in names:
            target.execute(row['sql'].replace('CREATE UNIQUE INDEX ', 'CREATE UNIQUE INDEX IF NOT EXISTS ', 1)
                           .replace('CREATE INDEX ', 'CREATE INDEX IF NOT EXISTS ', 1))


def copy_rows(source, target, table):
    cursor = source.execute('SELECT rowid,* FROM "'+table+'" ORDER BY rowid')
    names = ','.join('"'+r[0]+'"' for r in cursor.description)
    sql = 'INSERT INTO "'+table+'"('+names+') VALUES('+','.join('?' for _ in cursor.description)+')'
    while rows := cursor.fetchmany(128):
        target.executemany(sql, rows)


def initialize_split(config):
    if config.database.resolve() == config.library_database.resolve():
        raise ValueError('Library and workspace must use different databases')
    if config.library_dir.resolve() == config.data.resolve():
        raise ValueError('Library and workspace must use different resource directories')
    config.data.mkdir(parents=True, exist_ok=True)
    config.library_dir.mkdir(parents=True, exist_ok=True)
    config.papers.mkdir(exist_ok=True)
    with closing(template()) as schema:
        all_names = {r[0] for r in schema.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for path, names in ((config.library_database, LIBRARY_TABLES), (config.database, all_names-LIBRARY_TABLES)):
            with closing(sqlite3.connect(path)) as conn, conn:
                unexpected = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}-names
                if unexpected:
                    raise ValueError('Mixed database requires migration: '+', '.join(sorted(unexpected)))
                copy_schema(schema, conn, names)
                if 'library_state' in names:
                    from app.bank.collections import initialize as collections
                    collections(conn)
                    from app.bank.applicability import initialize as applicability
                    applicability(conn)
                    from app.storage.navigation_index import initialize as navigation
                    navigation(conn)
                    from app.storage.library_identity import initialize
                    initialize(conn)
                if 'papers' in names:
                    columns={r[1] for r in conn.execute('PRAGMA table_info(papers)')}
                    for name,kind in (('updated_at','TEXT'),('archived_at','TEXT'),('score_confirmed_at','TEXT'),('math_type','INTEGER')):
                        if name not in columns:conn.execute('ALTER TABLE papers ADD COLUMN '+name+' '+kind)
                    conn.execute('UPDATE papers SET updated_at=created_at WHERE updated_at IS NULL')
                    from app.learning.dates import initialize as initialize_dates
                    initialize_dates(conn)
                for name in ('preferences', 'knowledge_nodes'):
                    if name in names and not conn.execute('SELECT 1 FROM '+name+' LIMIT 1').fetchone():
                        copy_rows(schema, conn, name)
    save_location(config)


def migrate_legacy(source_dir, config):
    if config.database.exists() or config.library_database.exists():
        raise ValueError('Migration targets must be new; existing stores are never overwritten')
    config.data.parent.mkdir(parents=True,exist_ok=True)
    config.library_dir.parent.mkdir(parents=True,exist_ok=True)
    from dataclasses import replace
    with tempfile.TemporaryDirectory(dir=config.data.parent,prefix='.workspace-migration-') as work, \
         tempfile.TemporaryDirectory(dir=config.library_dir.parent,prefix='.library-migration-') as shared:
        staged=replace(config,data=Path(work)/'workspace',database=Path(work)/'workspace'/config.database.name,library=Path(shared)/'library')
        result=_migrate_legacy_to(source_dir,staged,config)
        if config.data.exists() and any(config.data.iterdir()):
            raise ValueError('Migration workspace directory is not empty')
        if config.library_dir.exists() and any(config.library_dir.iterdir()):
            raise ValueError('Migration library directory is not empty')
        if config.data.exists():config.data.rmdir()
        if config.library_dir.exists():config.library_dir.rmdir()
        staged.library_dir.rename(config.library_dir)
        try:staged.data.rename(config.data)
        except BaseException:
            config.library_dir.rename(staged.library_dir)
            raise
        save_location(config)
    return {**result,'workspace':str(config.data),'library':str(config.library_dir)}


def _migrate_legacy_to(source_dir, config, final_config):
    """One-time copy into empty stores. The original installation is retained."""
    from app.storage.provenance import capture_provenance
    source_dir = Path(source_dir).resolve()
    if config.database.exists() or config.library_database.exists():
        raise ValueError('Migration targets must be new; existing stores are never overwritten')
    if config.data.resolve().is_relative_to(source_dir) or config.library_dir.resolve().is_relative_to(source_dir):
        raise ValueError('Migration destinations must be outside the legacy directory')
    session_path = source_dir/'agent-session.db'
    if session_path.is_file():
        with closing(sqlite3.connect(session_path)) as session:
            row = session.execute('SELECT payload FROM session WHERE id=1').fetchone()
        state = json.loads(row[0]) if row else {}
        if state.get('active_request') or state.get('external_control'):
            raise ValueError('Finish or release the active learning session before migration')
    source_path = source_dir/'mathlens.db'
    with closing(sqlite3.connect(source_path.as_uri()+'?mode=ro',uri=True)) as source:
        source.row_factory = sqlite3.Row
        if source.execute("SELECT 1 FROM workflow_jobs WHERE status IN ('queued','dispatching','running') LIMIT 1").fetchone():
            raise ValueError('Finish pending workflows before migration')
        with closing(sqlite3.connect(':memory:')) as snapshot:
            snapshot.row_factory = sqlite3.Row
            source.backup(snapshot)
            initialize_split(config)
            names = {r[0] for r in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for path, selected in ((config.library_database,names & LIBRARY_TABLES), (config.database,names-LIBRARY_TABLES)):
                with closing(sqlite3.connect(path)) as target, target:
                    # Collection guards stay enabled during migration: install
                    # the source's registry before copying its question rows.
                    for name in sorted(selected,key=lambda n:(n!='bank_collections',n)):
                        target.execute('DELETE FROM "'+name+'"')
                        copy_rows(snapshot,target,name)
                    if path == config.library_database:
                        if 'bank_collections' not in selected:
                            from app.bank.collections import assign_legacy
                            assign_legacy(target)
                        for annotation in snapshot.execute('SELECT * FROM question_annotations'):
                            try:proof = capture_provenance(snapshot, annotation)
                            except ValueError:proof = None
                            if proof is not None:
                                target.execute('INSERT INTO annotation_provenance VALUES(?,?)',
                                               (annotation['id'],json.dumps(proof,ensure_ascii=False,sort_keys=True)))
                        target.execute("UPDATE knowledge_catalog_releases SET reviewer='catalog-maintenance' WHERE reviewer LIKE 'agent:%'")
                    else:
                        for row in target.execute('SELECT id,source_path FROM papers WHERE source_path IS NOT NULL').fetchall():
                            old = Path(row[1])
                            if not old.is_absolute():old = config.root/old
                            if old.resolve().is_relative_to(source_dir):
                                target.execute('UPDATE papers SET source_path=? WHERE id=?',
                                               (old.resolve().relative_to(source_dir).as_posix(),row[0]))
            for entry in source_dir.iterdir():
                if entry.name in ('mathlens.db','backups','trash','server.json','workspace.json') or entry.name.endswith(('-journal','-wal','-shm','.log')):
                    continue
                target_root = config.library_dir if entry.name in ('bank-assets','knowledge-sources') else config.data
                target = target_root/entry.name
                if entry.is_symlink():continue
                if entry.is_dir():shutil.copytree(entry,target,dirs_exist_ok=True)
                elif entry.name == 'agent-session.db':
                    with closing(sqlite3.connect(entry)) as old,closing(sqlite3.connect(target)) as new:old.backup(new)
                else:shutil.copy2(entry,target)
            if (config.data/'agent-session.db').is_file():
                from app.storage.maintenance import _rebase_paths
                with closing(sqlite3.connect(config.data/'agent-session.db')) as session,session:
                    row=session.execute('SELECT payload FROM session WHERE id=1').fetchone()
                    if row:
                        value=_rebase_paths(json.loads(row[0]),source_dir,final_config.data)
                        session.execute('UPDATE session SET payload=? WHERE id=1',(json.dumps(value,ensure_ascii=False),))
    return {'workspace':str(config.data),'library':str(config.library_dir),'legacy_preserved':str(source_dir)}
