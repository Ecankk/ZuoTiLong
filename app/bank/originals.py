"""Uploaded exam questions are never fresh selection candidates."""
from app.bank.access import policy_group
from app.bank.paper_candidates import location


def uploaded_originals(conn):
    from app.bank.capture_view import active
    view=active(conn)
    if view is not None and hasattr(view,'uploaded_originals'):return view.uploaded_originals
    papers={r['id']:dict(r) for r in conn.execute("SELECT * FROM papers WHERE source_path IS NOT NULL AND source_path!=''")}
    identities=list(conn.execute('SELECT bank_id,math_type,year FROM bank_identity'))
    seeds={}
    def add(bid,pid):
        if bid:seeds.setdefault(bid,set()).add(pid)
    for pid,paper in papers.items():
        loc=location(paper)
        if loc['status']=='located' and loc['math_type'] in (1,2,3):
            for row in identities:
                if str(row['year'])==loc['year'] and row['math_type']==loc['math_type']:add(row['bank_id'],pid)
    for row in conn.execute('SELECT paper_id,match_bank_id FROM questions WHERE match_bank_id IS NOT NULL'):
        if row['paper_id'] in papers:add(row['match_bank_id'],row['paper_id'])
    for row in conn.execute('SELECT q.paper_id,b.bank_id FROM paper_question_bindings b JOIN questions q ON q.id=b.question_id'):
        if row['paper_id'] in papers:add(row['bank_id'],row['paper_id'])
    result={}
    visited={}
    for bid,pids in seeds.items():
        group=visited.get(bid)
        if group is None:
            group=policy_group(conn,bid)
            for other in group:visited[other]=group
        for other in group:result.setdefault(other,set()).update(pids)
    result={bid:sorted(pids) for bid,pids in result.items()}
    if view is not None:view.uploaded_originals=result
    return result
