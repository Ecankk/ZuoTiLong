"""Small serialization helpers shared by services and storage."""
import json
from datetime import datetime,timezone

def now_iso(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def as_json(row): return dict(row) if row else None
def json_load(value,fallback=None):
    try:return json.loads(value) if value else fallback
    except (ValueError,TypeError):return fallback
def rows(conn,sql,params=()):return [dict(r) for r in conn.execute(sql,params)]
