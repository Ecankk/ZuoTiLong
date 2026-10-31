"""Explicit shared-index provenance, independent of Agent execution receipts."""
from app.storage.boundaries import table_exists
import json
from app.common import now_iso


def exists(conn):
    return bool(table_exists(conn, 'prepared_annotation_ids'))


def initialize(conn):
    for sql in (
        'CREATE TABLE IF NOT EXISTS prepared_annotation_ids(id TEXT PRIMARY KEY)',
        '''CREATE TABLE IF NOT EXISTS annotation_cache_packages(
        sha256 TEXT PRIMARY KEY,payload_json TEXT NOT NULL,imported_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS annotation_cache_state(
        package_sha256 TEXT PRIMARY KEY REFERENCES annotation_cache_packages(sha256),
        enabled INTEGER NOT NULL CHECK(enabled IN (0,1)))''',
        '''CREATE TABLE IF NOT EXISTS annotation_cache_imports(
        id TEXT PRIMARY KEY,package_sha256 TEXT NOT NULL REFERENCES annotation_cache_packages(sha256),
        preview_sha256 TEXT NOT NULL,created_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS imported_question_annotations(
        id TEXT PRIMARY KEY REFERENCES prepared_annotation_ids(id),
        package_sha256 TEXT NOT NULL REFERENCES annotation_cache_packages(sha256),
        entry_sha256 TEXT NOT NULL,bank_id TEXT NOT NULL REFERENCES bank_questions(id),
        entity_id TEXT NOT NULL,content_revision TEXT NOT NULL,material_revision TEXT NOT NULL,
        catalog_revision TEXT NOT NULL REFERENCES knowledge_catalog_releases(id),
        dependencies_json TEXT NOT NULL,metadata_json TEXT NOT NULL,created_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS imported_annotation_topics(
        annotation_id TEXT NOT NULL REFERENCES imported_question_annotations(id),
        topic_id TEXT NOT NULL,role TEXT NOT NULL,stages_json TEXT NOT NULL,
        PRIMARY KEY(annotation_id,topic_id))''',
        'CREATE INDEX IF NOT EXISTS idx_imported_annotation_bank ON imported_question_annotations(bank_id)',
        'CREATE INDEX IF NOT EXISTS idx_imported_annotation_topic ON imported_annotation_topics(topic_id)',
    ):
        conn.execute(sql)
    # Backfill identities only. No imported index, task, read receipt or learner
    # event is created. INSERT OR IGNORE preserves established global order.
    conn.execute('''INSERT OR IGNORE INTO prepared_annotation_ids(id)
                    SELECT id FROM question_annotations ORDER BY rowid''')


def register(conn, annotation_id):
    conn.execute('INSERT OR IGNORE INTO prepared_annotation_ids(id) VALUES(?)', (annotation_id,))


def record(conn, annotation_id):
    row = conn.execute('SELECT * FROM question_annotations WHERE id=?', (annotation_id,)).fetchone()
    if row:
        return dict(row)
    if not exists(conn):
        return None
    row = conn.execute('SELECT * FROM imported_question_annotations WHERE id=?', (annotation_id,)).fetchone()
    if not row:
        return None
    value = dict(row)
    metadata = json.loads(value['metadata_json'])
    value.update(rule_revision=metadata['rule_revision'], result_id=None,
                 payload_json=json.dumps(analysis(value), ensure_ascii=False, sort_keys=True),
                 identity_json=json.dumps({value['bank_id']: value['content_revision']}, sort_keys=True),
                 cache_provenance={'package_sha256': value['package_sha256'], 'entry_sha256': value['entry_sha256']})
    return value


def analysis(row):
    metadata = json.loads(row['metadata_json'])
    return {'status': 'ready', 'bindings': metadata['bindings'], 'methods': [],
            'method_hashes': metadata['method_hashes'], 'checkpoints': [], 'fingerprint': None,
            'reference_reasoning': None,
            'answer_check': {'status': 'consistent', 'note': '共享来源声明参考一致，本机仅核对材料与知识依赖。'},
            'unmatched_topics': [], 'limitations': ['共享索引不包含解题推导，不代表本机重新解题；选题/批改仍实际读取对应材料。']}


def manifest(conn, digest):
    values = {r['id']: digest(dict(r)) for r in conn.execute('SELECT * FROM question_annotations')}
    if exists(conn):
        values.update({r[0]: digest(record(conn, r[0])) for r in conn.execute('SELECT id FROM imported_question_annotations')})
    return values


def enabled(conn, package_sha256):
    row = conn.execute('SELECT enabled FROM annotation_cache_state WHERE package_sha256=?', (package_sha256,)).fetchone()
    return bool(row and row[0])


def candidates(conn, bank_id):
    if not exists(conn):
        return []
    return [dict(r) for r in conn.execute('''SELECT a.*,p.rowid AS order_id
        FROM imported_question_annotations a JOIN prepared_annotation_ids p ON p.id=a.id
        JOIN annotation_cache_state s ON s.package_sha256=a.package_sha256
        WHERE a.bank_id=? AND s.enabled=1 ORDER BY p.rowid DESC''', (bank_id,))]


def listing(conn):
    if not exists(conn):
        return []
    return [dict(r) for r in conn.execute('''SELECT p.sha256,p.imported_at,s.enabled,
        (SELECT count(*) FROM imported_question_annotations a WHERE a.package_sha256=p.sha256) AS local_records
        FROM annotation_cache_packages p JOIN annotation_cache_state s ON s.package_sha256=p.sha256
        ORDER BY p.rowid DESC''')]


def entry(conn, annotation):
    row = conn.execute('SELECT payload_json FROM annotation_cache_packages WHERE sha256=?',
                       (annotation['package_sha256'],)).fetchone()
    if not row:
        raise ValueError('共享标注索引出处缺失')
    package = json.loads(row[0])
    return next((item for item in package['entries'] if item['sha256'] == annotation['entry_sha256']), None)
