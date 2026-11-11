"""Persist source singletons; mathematical identity is never inferred at startup."""
import json
import uuid
from app.common import now_iso
from app.knowledge.catalog import digest


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
