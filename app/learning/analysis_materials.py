"""Captured paper references and explicit question coverage, without model recall."""
from app.bank import exam_identity,paper_candidates,annotations
from app.bank.access import require_access

def expectations(conn,paper):
    rows=list(conn.execute('SELECT number,source_text FROM questions WHERE paper_id=?',(paper['id'],)))
    known=sorted({int(r[0]) for r in rows
                  if str(r[0]).isdigit() and 1<=int(r[0])<=100})
    # Analysis-created missing questions have no extraction source_text. Keep
    # their numbers in the report, but still identify the local segmentation gap.
    extracted={int(r[0]) for r in rows if r[1] is not None and str(r[0]).isdigit() and 1<=int(r[0])<=100}
    location=paper_candidates.location(dict(paper));numbers=list(known)
    if location:
        numbers += [r[0] for r in conn.execute('SELECT number FROM bank_identity WHERE year=? AND math_type=? AND number BETWEEN 1 AND 100',(str(location['year']),location['math_type']))]
    expected=max(numbers,default=0)
    return dict(expected_count=expected,known_question_numbers=known,missing_question_numbers=sorted(set(range(1,expected+1))-(extracted or set(known))))

def capture(conn,data,paper):
    coverage=expectations(conn,paper);entries=[];missing=[];location=paper_candidates.location(dict(paper))
    if location:
        for number in range(1,coverage['expected_count']+1):
            selected=exam_identity.select(conn,location['year'],location['math_type'],number);bid=selected['matched_bank_id']
            if not bid:continue
            try:
                require_access(conn,bid,internal=True)
                material=annotations.materials(conn,data,bid)
            except ValueError as exc:
                missing.append(dict(number=number,bank_id=bid,reason=str(exc)));continue
            entries.append(dict(number=number,bank_id=bid,materials=material,
                reference_available=bool(set(material)&{'answer','analysis'})))
    return {**coverage,'entries':entries,'unavailable_references':missing}
