"""Validated navigation evidence reused only inside one read-only task capture."""
from contextvars import ContextVar
from contextlib import contextmanager,closing
import json
ACTIVE=ContextVar('bank_capture_view',default=None)

def active(conn):
    value=ACTIVE.get()
    return value if value is not None and value.conn is conn else None

@contextmanager
def capture(conn,data):
    from app.storage.boundaries import workspace_config
    from app.storage.navigation_index import NavigationIndex
    from app.services.knowledge_links import KnowledgeLinksService
    from app.storage.database import Database
    from app.bank.annotation_view import AnnotationReadView
    from app.knowledge import index
    config=workspace_config(data);view=AnnotationReadView(conn,data)
    view.access_cache={};view.plan_cache={};view.history_cache={}
    from app.bank.identity_reviews import confirmed_pairs
    parents={};hashes={};exams={}
    def find(bid):
        parents.setdefault(bid,bid)
        while parents[bid]!=bid:parents[bid]=parents[parents[bid]];bid=parents[bid]
        return bid
    def join(a,b):parents[find(a)]=find(b)
    for r in conn.execute('SELECT * FROM bank_identity'):
        bid=r['bank_id'];find(bid)
        if r['sha256']:join(bid,hashes.setdefault(r['sha256'],bid))
        if r['math_type'] in (1,2,3) and str(r['year']).isascii() and str(r['year']).isdigit() and len(str(r['year']))==4 and r['number'] and r['number']>0:
            join(bid,exams.setdefault((r['math_type'],r['year'],r['number']),bid))
    for a,b in list(conn.execute('SELECT left_id,right_id FROM bank_links'))+confirmed_pairs(conn):join(a,b)
    groups={}
    for bid in parents:groups.setdefault(find(bid),set()).add(bid)
    view.policy_groups={bid:group for group in groups.values() for bid in group}
    service=KnowledgeLinksService(config,Database(config));store=NavigationIndex(config)
    store.bank(conn,index.catalog(conn),service._build_bank_item)
    with closing(store.open()) as cache:
        view.annotations={}
        for row in cache.execute('SELECT bank_id,payload,materials FROM items'):
            view.annotations[row['bank_id']]=json.loads(row['payload']).get('_annotation')
            view._materials[row['bank_id']]=json.loads(row['materials'])
    token=ACTIVE.set(view)
    try:yield view
    finally:ACTIVE.reset(token)
