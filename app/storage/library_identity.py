"""Stable library lineage and cheap progress; ordinary writes advance revision."""
from contextlib import closing
import hashlib,json,sqlite3,uuid
from pathlib import Path

SCHEME='mathlens.library-identity/v1'


def initialize(conn):
    from app.storage.boundaries import LIBRARY_TABLES
    conn.execute('''CREATE TABLE IF NOT EXISTS library_state(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),library_id TEXT NOT NULL,revision INTEGER NOT NULL)''')
    conn.execute('INSERT OR IGNORE INTO library_state VALUES(1,?,0)',('library-'+uuid.uuid4().hex,))
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in sorted((LIBRARY_TABLES & tables)-{'library_state'}):
        for action in ('INSERT','UPDATE','DELETE'):
            conn.execute('CREATE TRIGGER IF NOT EXISTS revision_'+table+'_'+action.lower()+' AFTER '+action+' ON "'+table+'" '
                         'BEGIN UPDATE library_state SET revision=revision+1 WHERE singleton=1; END')


def read(library):
    library=Path(library).resolve();path=library/'library.db'
    if not path.is_file():raise ValueError('library_missing：通用库不存在，请先恢复对应题库')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as conn:
        exists=conn.execute("SELECT 1 FROM sqlite_master WHERE name='library_state'").fetchone()
    if not exists:
        with closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)) as conn,conn:
            conn.execute('BEGIN IMMEDIATE');initialize(conn)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('BEGIN')
        row=conn.execute('SELECT library_id,revision FROM library_state WHERE singleton=1').fetchone()
        if not row:raise ValueError('题库标识缺失，请重新初始化题库')
        annotations=conn.execute('SELECT count(*),coalesce(max(rowid),0) FROM question_annotations').fetchone()
        catalog=conn.execute('SELECT release_id FROM knowledge_catalog_state LIMIT 1').fetchone()
        versions=list(conn.execute('SELECT source_id,revision,count(*) FROM bank_source_records GROUP BY source_id,revision ORDER BY source_id,revision'))
        versions+=list(conn.execute('SELECT source,revision,1 FROM knowledge_source_versions ORDER BY source,revision'))
        source_sha=hashlib.sha256(json.dumps(versions,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return dict(scheme=SCHEME,library_id=row[0],location=str(library),version=dict(revision=row[1],
        catalog_revision=catalog[0] if catalog else None,annotation_count=annotations[0],annotation_max_rowid=annotations[1],source_versions_sha256=source_sha))


def compare(saved, actual):
    if saved.get('scheme')!=SCHEME:raise ValueError('个人备份题库身份格式不受支持，请重新生成备份')
    if saved.get('library_id')!=actual['library_id']:raise ValueError('library_mismatch：通用库标识不同，请选择同一题库或恢复对应题库备份')
    before=saved['version']['revision'];after=actual['version']['revision']
    return 'newer' if after>before else 'older' if after<before else 'same'
