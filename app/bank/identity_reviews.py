"""Audited, reversible identity evidence; reference quality remains independent."""
from app.storage.boundaries import table_exists
import json
import uuid
from app.knowledge.catalog import digest, encode
from app.common import now_iso


def initialize(conn):
    if table_exists(conn,'bank_identity_reviews'):return
    conn.execute('''CREATE TABLE IF NOT EXISTS bank_identity_reviews(
        id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,
        left_id TEXT NOT NULL REFERENCES bank_questions(id),
        right_id TEXT NOT NULL REFERENCES bank_questions(id),
        operation TEXT NOT NULL CHECK(operation IN ('confirm','revoke')),
        payload_sha256 TEXT NOT NULL,preview_sha256 TEXT NOT NULL,
        identity_tokens_json TEXT NOT NULL,before_json TEXT NOT NULL,
        reason TEXT NOT NULL,created_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_bank_identity_pair ON bank_identity_reviews(left_id,right_id)')


def _exists(conn):
    return bool(table_exists(conn, 'bank_identity_reviews'))


def identity_tokens(conn, bank_ids=None):
    # Registration is the source-version boundary. A reference update must not
    # revoke question identity; a registered question-pixel/text change must.
    query = 'SELECT i.bank_id,i.sha256,b.stem FROM bank_identity i JOIN bank_questions b ON b.id=i.bank_id'
    ids = [] if bank_ids is None else sorted(set(bank_ids))
    if bank_ids is not None:
        if not ids:return {}
        query += ' WHERE i.bank_id IN (' + ','.join('?' for _ in ids) + ')'
    return {r['bank_id']: digest({'pixels': r['sha256']} if r['sha256'] else {'text': r['stem']})
            for r in conn.execute(query, ids)}


def confirmed_pairs(conn):
    if not _exists(conn):
        return []
    latest = {}
    for row in conn.execute('SELECT * FROM bank_identity_reviews ORDER BY rowid'):
        latest[(row['left_id'], row['right_id'])] = row
    if not latest:return []
    tokens = identity_tokens(conn, {bid for pair,row in latest.items() if row['operation']=='confirm' for bid in pair})
    return [pair for pair, row in latest.items()
            if row['operation'] == 'confirm'
            and json.loads(row['identity_tokens_json']) == {bid: tokens.get(bid) for bid in pair}]


def _pair(conn, left_id, right_id):
    if (not isinstance(left_id, str) or not isinstance(right_id, str)
            or not 1 <= len(left_id) <= 180 or not 1 <= len(right_id) <= 180 or left_id == right_id):
        raise ValueError('须提供两个不同的有效题目ID')
    pair = tuple(sorted((left_id, right_id)))
    if any(not conn.execute('SELECT 1 FROM bank_identity WHERE bank_id=?', (bid,)).fetchone() for bid in pair):
        raise ValueError('待核题目不存在或尚未登记身份')
    return pair


def preview(conn, data, left_id, right_id, operation):
    from app.bank.access import aliases
    from app.bank.annotations import materials, reference_signature
    if operation not in ('confirm', 'revoke'):
        raise ValueError('同题操作只能为confirm或revoke')
    pair = _pair(conn, left_id, right_id)
    sources = {bid: materials(conn, data, bid) for bid in pair}
    tokens = identity_tokens(conn, pair)
    latest = conn.execute('''SELECT id,operation FROM bank_identity_reviews
        WHERE left_id=? AND right_id=? ORDER BY rowid DESC LIMIT 1''', pair).fetchone() if _exists(conn) else None
    legacy = [dict(r) for r in conn.execute('SELECT * FROM bank_links WHERE (left_id=? AND right_id=?) OR (left_id=? AND right_id=?)', (*pair, *reversed(pair)))]
    value = {'left_id': pair[0], 'right_id': pair[1], 'operation': operation,
             'identity_tokens': {bid: tokens[bid] for bid in pair},
             'materials': {bid: {role: content['sha256'] for role, content in source.items()} for bid, source in sources.items()},
             'groups_before': {bid: sorted(aliases(conn, bid)) for bid in pair},
             'previous_review': dict(latest) if latest else None, 'legacy_edges': legacy,
             'reference_materials_identical': reference_signature(sources[pair[0]]) == reference_signature(sources[pair[1]])}
    return {**value, 'preview_sha256': digest(value),
            'scope': '只确认题目条件、目标、选项和图形相同；不确认不同参考正确，也不修改材料、作答或画像。',
            'registration_policy': '题目重新登记后若像素或正文身份变化，旧确认失效；参考版本仍逐份实际核验。'}


def apply(conn, data, body):
    from app.bank.access import aliases
    if body.get('confirmed') is not True:
        raise ValueError('须明确确认已核对题目身份；参考质量另行核验')
    try:
        request_id = str(uuid.UUID(body['request_id']))
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError('同题维护请求标识无效') from None
    reason = body.get('reason')
    if (not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 1500
            or any(ord(c) < 32 and c not in '\n\r\t' for c in reason)):
        raise ValueError('须记录8–1500字的具体题目对照依据')
    pair = _pair(conn, body.get('left_id'), body.get('right_id'))
    payload = {'left_id': pair[0], 'right_id': pair[1], 'operation': body.get('operation'),
               'expected_preview_sha256': body.get('expected_preview_sha256'), 'reason': reason.strip()}
    sha = digest(payload)
    prior = conn.execute('SELECT * FROM bank_identity_reviews WHERE request_id=?', (request_id,)).fetchone()
    if prior:
        if prior['payload_sha256'] != sha:
            raise ValueError('同一同题维护请求不能更换内容')
        latest = conn.execute('SELECT id FROM bank_identity_reviews WHERE left_id=? AND right_id=? ORDER BY rowid DESC LIMIT 1', pair).fetchone()
        confirmed = pair in confirmed_pairs(conn)
        return {'review_id': prior['id'], 'reused': True,
                'still_current': latest['id'] == prior['id'] and (prior['operation'] == 'revoke' or confirmed),
                'currently_confirmed': confirmed, 'group': sorted(aliases(conn, pair[0]))}
    state = preview(conn, data, pair[0], pair[1], payload['operation'])
    if payload['expected_preview_sha256'] != state['preview_sha256']:
        raise ValueError('材料、身份或同题关系已变化，请重新预览并核对')
    if payload['operation'] == 'revoke':
        previous = state['previous_review']
        if not state['legacy_edges'] and (not previous or previous['operation'] != 'confirm'):
            raise ValueError('该题对没有可撤回的人工确认；像素同题或其他传递路径须分别核对')
    review_id = 'identity-review-' + uuid.uuid5(uuid.NAMESPACE_URL, request_id).hex
    conn.execute('INSERT INTO bank_identity_reviews VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                 (review_id, request_id, *pair, payload['operation'], sha, state['preview_sha256'],
                  encode(state['identity_tokens']), encode(state), reason.strip(), now_iso()))
    # Preserve old confirmations in before_json, including their original reason.
    # New decisions use the versioned history, never an unversioned projection.
    conn.execute('DELETE FROM bank_links WHERE (left_id=? AND right_id=?) OR (left_id=? AND right_id=?)', (*pair, *reversed(pair)))
    return {'review_id': review_id, 'reused': False, 'still_current': True,
            'currently_confirmed': pair in confirmed_pairs(conn), 'group': sorted(aliases(conn, pair[0])),
            'reference_quality_inherited': False, 'learner_evidence_modified': False}
