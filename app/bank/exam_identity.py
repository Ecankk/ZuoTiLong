"""Source-independent exam navigation; it never asserts mathematical equivalence."""
import json
import math


def metadata(conn, bank_id):
    row = conn.execute('SELECT metadata_json FROM bank_resources WHERE bank_id=?', (bank_id,)).fetchone()
    value = json.loads(row[0]) if row else {}
    kind = value.get('question_type')
    kind = {'choice':'选择题', 'fill':'填空题', 'proof':'解答题'}.get(kind, kind)
    # Legacy S01 records keep their upstream explicit numeric enum.
    if not kind and value.get('source_url') == 'https://github.com/lx-ruc/kaoyanshuxue' and type(value.get('type')) is int:
        kind = {1:'选择题', 2:'填空题', 3:'解答题'}.get(value['type'])
    score = value.get('max_score', value.get('score'))
    return dict(question_type=kind if isinstance(kind, str) and kind.strip() else None,
                max_score=score if type(score) in (int, float) and math.isfinite(score) and score >= 0 else None)


def source_key(conn, bank_id):
    row = conn.execute('''SELECT r.metadata_json,b.source,b.source_ref FROM bank_resources r
        JOIN bank_questions b ON b.id=r.bank_id WHERE r.bank_id=?''', (bank_id,)).fetchone()
    value = json.loads(row['metadata_json']) if row else {}
    source = value.get('source_id') or ('S01' if value.get('source_url') == 'https://github.com/lx-ruc/kaoyanshuxue' else '')
    source = source or (row['source'] if row and row['source'].startswith('S') else '~legacy')
    return source, str(value.get('source_uid') or (row['source_ref'] if row else None) or bank_id), bank_id


def candidates(conn, year, math_type, number):
    ids = [r[0] for r in conn.execute('''SELECT i.bank_id FROM bank_identity i
        JOIN bank_resources r ON r.bank_id=i.bank_id
        WHERE i.year=? AND i.math_type=? AND i.number=?''', (str(year), math_type, number))]
    return sorted(ids, key=lambda bid: source_key(conn, bid))


def select(conn, year, math_type, number):
    ids = candidates(conn, year, math_type, number)
    values = [metadata(conn, bid) for bid in ids]
    # Missing values can be filled from a nonconflicting known source.
    combined = {}
    for field in ('question_type', 'max_score'):
        known = {value[field] for value in values if value[field] is not None}
        combined[field] = next(iter(known)) if len(known) == 1 else None
    return dict(combined, matched_bank_id=ids[0] if ids else None)
