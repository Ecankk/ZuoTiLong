"""Persist source singletons; mathematical identity is never inferred at startup."""
import json
import uuid
from app.common import now_iso
from app.knowledge.catalog import digest
from app.bank.source_records import canonical


def record_signature(record):
    """Stable complete-content signature for one standard source record.

    This deliberately excludes answer, analysis, source and locator.  It is
    an exact content key, never a semantic similarity score.
    """
    def part(value):
        return {'text': value.get('text', ''),
                'images': sorted(image.get('sha256') for image in value.get('images', []))}
    payload={'question_type': record.get('question_type'),
             'stem': part(record.get('stem', {})),
             'options': [{'label': option.get('label'), 'content': part(option.get('content', {}))}
                         for option in sorted(record.get('options', []), key=lambda value: value.get('label', ''))]}
    figures=record.get('supplemental_figures', {})
    payload['supplemental_stem_images']=sorted(
        entry.get('image', {}).get('sha256')
        for entry in figures.get('entries', []) if entry.get('role') == 'stem')
    return digest(payload)


def member(conn, bank_id):
    return conn.execute('''SELECT m.bank_id,m.entity_id,m.identity_signature,m.signature_version,m.state,
                                  e.display_bank_id,e.collection_id,e.revision
                           FROM question_entity_members m JOIN question_entities e ON e.id=m.entity_id
                           WHERE m.bank_id=?''', (bank_id,)).fetchone()


def public_member(conn, bank_id):
    row=member(conn, bank_id)
    if row is None or row['state'] != 'confirmed':
        return None
    return row


def register_member(conn, bank_id, entity_id, signature, state='confirmed'):
    conn.execute('''INSERT INTO question_entity_members(bank_id,entity_id,identity_signature,signature_version,state)
                    VALUES(?,?,?,?,?)
                    ON CONFLICT(bank_id) DO UPDATE SET entity_id=excluded.entity_id,
                    identity_signature=excluded.identity_signature,signature_version=excluded.signature_version,
                    state=excluded.state''', (bank_id,entity_id,signature,'question_identity_signature/v1',state))


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS question_entities(
        id TEXT PRIMARY KEY,display_bank_id TEXT NOT NULL REFERENCES bank_questions(id),
        collection_id TEXT NOT NULL REFERENCES bank_collections(id),
        revision INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS question_entity_members(
        bank_id TEXT PRIMARY KEY REFERENCES bank_questions(id),
        entity_id TEXT NOT NULL REFERENCES question_entities(id),
        identity_signature TEXT,signature_version TEXT,
        state TEXT NOT NULL CHECK(state IN ('confirmed','pending')))''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_entity_members ON question_entity_members(entity_id)')
    conn.execute('''CREATE TABLE IF NOT EXISTS question_entity_events(
        id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,operation TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,plan_sha256 TEXT,before_json TEXT NOT NULL,
        after_json TEXT NOT NULL,evidence_json TEXT NOT NULL,created_at TEXT NOT NULL)''')
    # No UPDATE of historical bank rows; no material reads or cross-source links.
    missing=list(conn.execute('''SELECT b.id,b.collection_id FROM bank_questions b
        LEFT JOIN question_entity_members m ON m.bank_id=b.id WHERE m.bank_id IS NULL ORDER BY b.id'''))
    for bid,collection in missing:
        eid='entity-'+uuid.uuid4().hex;stamp=now_iso()
        after=dict(entity_id=eid,bank_id=bid,collection_id=collection)
        conn.execute('INSERT INTO question_entities VALUES(?,?,?,?,?)',(eid,bid,collection,1,stamp))
        conn.execute('INSERT INTO question_entity_members VALUES(?,?,NULL,NULL,?)',(bid,eid,'confirmed'))
        conn.execute('INSERT INTO question_entity_events VALUES(?,?,?,?,?,?,?,?,?)',
            ('entity-event-'+uuid.uuid4().hex,'singleton:'+bid,'singleton',digest(after),None,'{}',
             json.dumps(after,ensure_ascii=False,sort_keys=True),'{"basis":"source_singleton_only"}',stamp))
    return len(missing)
