"""Imported catalogue provenance, independent of AI tasks and learner records."""
from app.storage.boundaries import table_exists
import json
import uuid
from app.common import now_iso


def initialize(conn):
    for sql in (
        '''CREATE TABLE IF NOT EXISTS knowledge_catalog_packages(
        sha256 TEXT PRIMARY KEY,origin_catalog_revision TEXT NOT NULL,
        origin_content_sha256 TEXT NOT NULL,document_sha256 TEXT NOT NULL,
        payload_json TEXT NOT NULL,imported_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS knowledge_package_sources(
        package_sha256 TEXT NOT NULL REFERENCES knowledge_catalog_packages(sha256),
        source_version_id TEXT NOT NULL,source TEXT NOT NULL,revision TEXT NOT NULL,
        manifest_sha256 TEXT NOT NULL,references_json TEXT NOT NULL,
        PRIMARY KEY(package_sha256,source_version_id))''',
        '''CREATE TABLE IF NOT EXISTS knowledge_package_entries(
        package_sha256 TEXT NOT NULL,source_version_id TEXT NOT NULL,source_id TEXT NOT NULL,
        kind TEXT NOT NULL,content_sha256 TEXT NOT NULL,chapter_key TEXT NOT NULL,
        PRIMARY KEY(package_sha256,source_version_id,source_id),
        FOREIGN KEY(package_sha256,source_version_id)
        REFERENCES knowledge_package_sources(package_sha256,source_version_id))''',
        '''CREATE TABLE IF NOT EXISTS knowledge_package_activations(
        id TEXT PRIMARY KEY,package_sha256 TEXT NOT NULL REFERENCES knowledge_catalog_packages(sha256),
        previous_release_id TEXT REFERENCES knowledge_catalog_releases(id),
        release_id TEXT NOT NULL REFERENCES knowledge_catalog_releases(id),
        operation TEXT NOT NULL,created_at TEXT NOT NULL)''',
    ):
        conn.execute(sql)


def exists(conn):
    return bool(table_exists(conn, 'knowledge_catalog_packages'))


def source_known(conn, version, source_id):
    original = conn.execute('SELECT content_sha256 FROM knowledge_source_entries WHERE source_version_id=? AND id=?',
                            (version, source_id)).fetchone()
    imported = list(conn.execute('''SELECT DISTINCT content_sha256 FROM knowledge_package_entries
        WHERE source_version_id=? AND source_id=?''', (version, source_id))) if exists(conn) else []
    hashes = {r[0] for r in imported}
    if original:
        hashes.add(original[0])
    if len(hashes) > 1:
        raise ValueError('固定来源版本出现冲突散列，不能沿用共享目录')
    return bool(hashes)


def save(conn, package, encode):
    """Caller owns the transaction; no implicit commits or initialization."""
    sha = package['sha256']
    old = conn.execute('SELECT payload_json FROM knowledge_catalog_packages WHERE sha256=?', (sha,)).fetchone()
    if old:
        if json.loads(old[0]) != package:
            raise ValueError('同散列目录包内容冲突')
        return False
    for source in package['sources']:
        version = source['id']
        original = conn.execute('SELECT source,revision,manifest_sha256 FROM knowledge_source_versions WHERE id=?',
                                (version,)).fetchone()
        expected = (source['source'], source['revision'], source['manifest_sha256'])
        if original and tuple(original) != expected:
            raise ValueError('共享包与已有固定来源版本冲突')
        imported = conn.execute('''SELECT source,revision,manifest_sha256 FROM knowledge_package_sources
            WHERE source_version_id=?''', (version,)).fetchall()
        if any(tuple(r) != expected for r in imported):
            raise ValueError('共享包与历史来源出处冲突')
        for entry in source['entries']:
            actual = conn.execute('SELECT kind,content_sha256 FROM knowledge_source_entries WHERE source_version_id=? AND id=?',
                                  (version, entry['id'])).fetchone()
            pair = (entry['kind'], entry['content_sha256'])
            if actual and tuple(actual) != pair:
                raise ValueError('共享包与已有来源条目冲突')
            known = conn.execute('''SELECT kind,content_sha256 FROM knowledge_package_entries
                WHERE source_version_id=? AND source_id=?''', (version, entry['id'])).fetchall()
            if any(tuple(r) != pair for r in known):
                raise ValueError('共享包与历史来源条目冲突')
    conn.execute('INSERT INTO knowledge_catalog_packages VALUES(?,?,?,?,?,?)',
                 (sha, package['origin']['catalog_revision'], package['origin']['content_sha256'],
                  package['document_sha256'], encode(package), now_iso()))
    for source in package['sources']:
        conn.execute('INSERT INTO knowledge_package_sources VALUES(?,?,?,?,?,?)',
                     (sha, source['id'], source['source'], source['revision'], source['manifest_sha256'],
                      encode(source['references'])))
        for entry in source['entries']:
            conn.execute('INSERT INTO knowledge_package_entries VALUES(?,?,?,?,?,?)',
                         (sha, source['id'], entry['id'], entry['kind'], entry['content_sha256'], entry['chapter_key']))
    return True


def record_activation(conn, sha, previous, release, operation):
    conn.execute('INSERT INTO knowledge_package_activations VALUES(?,?,?,?,?,?)',
                 ('package-activation-'+uuid.uuid4().hex, sha, previous, release, operation, now_iso()))


def listing(conn):
    if not exists(conn):
        return []
    return [dict(row) for row in conn.execute('''SELECT sha256,origin_catalog_revision,document_sha256,imported_at
        FROM knowledge_catalog_packages ORDER BY rowid DESC''')]


def source_metadata(conn, version):
    if not exists(conn):
        return None
    row = conn.execute('''SELECT source_version_id id,source,revision,manifest_sha256,references_json
        FROM knowledge_package_sources WHERE source_version_id=? ORDER BY rowid DESC LIMIT 1''', (version,)).fetchone()
    return {**dict(row), 'references': json.loads(row['references_json'])} if row else None


def entry_metadata(conn, version, source_id):
    if not exists(conn):
        return None
    row = conn.execute('''SELECT source_id id,kind,content_sha256,chapter_key FROM knowledge_package_entries
        WHERE source_version_id=? AND source_id=? ORDER BY rowid DESC LIMIT 1''', (version, source_id)).fetchone()
    return dict(row) if row else None


def all_sources(conn):
    if not exists(conn):
        return []
    ids = [r[0] for r in conn.execute('SELECT DISTINCT source_version_id FROM knowledge_package_sources ORDER BY source_version_id')]
    return [source_metadata(conn, version) for version in ids]


def all_entries(conn):
    if not exists(conn):
        return []
    return [dict(r) for r in conn.execute('''SELECT DISTINCT source_version_id,source_id id,kind,content_sha256,chapter_key
        FROM knowledge_package_entries ORDER BY source_version_id,source_id''')]


def check_raw_source(conn, value, version):
    """A later original-source import must match already accepted anchors."""
    known = source_metadata(conn, version)
    if not known:
        return
    if (known['source'], known['revision'], known['manifest_sha256']) != (value['source'], value['revision'], value['manifest_sha256']):
        raise ValueError('原文来源版本与已接受的共享目录出处冲突')
    actual = {e['id']: (e['kind'], e['record']['content_sha256']) for e in value['entries']}
    for row in conn.execute('''SELECT DISTINCT source_id,kind,content_sha256 FROM knowledge_package_entries
        WHERE source_version_id=?''', (version,)):
        if actual.get(row['source_id']) != (row['kind'], row['content_sha256']):
            raise ValueError('原文来源条目与已接受的共享目录出处冲突')
