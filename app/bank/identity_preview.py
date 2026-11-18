"""Read-only duplicate evidence; never attach members or publish decisions."""
from collections import defaultdict
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from app.bank import source_records as r
from app.bank.question_identity import signature,text


def rows(conn,table):
    return list(conn.execute('SELECT * FROM '+table)) if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() else []


def preview(library,*,completeness=None):
    library=Path(library).resolve();path=library/'library.db'
    if not path.is_file():raise ValueError('通用库不存在')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as conn:
        conn.row_factory=sqlite3.Row;conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
        return _preview(conn,library,completeness or {})


def _preview(conn,library,proofs):
    banks=rows(conn,'bank_questions');resources={x['bank_id']:x for x in rows(conn,'bank_resources')}
    standards={x['bank_id']:x for x in rows(conn,'bank_source_records')}
    identities={x['bank_id']:x for x in rows(conn,'bank_identity')}
    members={x['bank_id']:x for x in rows(conn,'question_entity_members')}
    details={};signatures={};answers={};question_roles={};hashes={};buckets=defaultdict(set);diagnostics=[];invalid=set()
    for bank in banks:
        bid=bank['id'];saved=standards.get(bid);res=resources.get(bid)
        meta=json.loads(res['metadata_json'] or '{}') if res else {}
        identity=identities.get(bid);issues=[]
        known={};expected_paths={}
        for part in meta.get('resources',{}).values():
            for im in part.get('images',[])+([part['display_image']] if part.get('display_image') else []):
                installed=im['path'].replace('\\','/')
                known[im['sha256']]=installed;expected_paths[installed]=im['sha256']
        for entry in meta.get('supplemental_figures',{}).get('entries',[]):
            im=entry['image'];known[im['sha256']]=im['path'].replace('\\','/')
        def image(path,expected=None):
            path=path.replace('\\','/')
            try:
                expected=expected or expected_paths.get(path)
                actual=r.asset_path(library,path)
                if actual not in hashes:hashes[actual]=r.sha256(actual.read_bytes())
                sha=hashes[actual]
                if expected and expected!=sha:issues.append('image_hash_mismatch')
                return dict(path=path,sha256=sha,media_type='image/png')
            except (OSError,ValueError):
                issues.append('image_missing_or_unsafe');return dict(path=path,sha256=expected or '0'*64,media_type='image/png')
        if saved:
            record=deepcopy(json.loads(saved['record_json']))
            # Original source paths need not exist in the installed library.
            for part in [record['stem'],record['answer'],*[o['content'] for o in record['options']]]:
                for im in part['images']:
                    if im['sha256'] in known:im['path']=known[im['sha256']]
            if 'supplemental_figures' in record:
                for e in record['supplemental_figures']['entries']:
                    im=e['image']
                    if im['sha256'] in known:im['path']=known[im['sha256']]
            if r.display(record,'stem')!=(bank['stem'] or ''):issues.append('source_display_mismatch')
        else:
            kind=meta.get('question_type')
            if kind not in ('choice','fill','proof'):
                kind={1:'choice',2:'fill',3:'proof'}.get(meta.get('type')) if meta.get('source_url','').endswith('kaoyanshuxue') else None
            record=dict(question_type=kind,stem=r.resource(bank['stem'] or '',[image(res['question_path'])] if res and res['question_path'] else []),
                        options=[],answer=r.resource(bank['answer'] or ''))
        sig=signature(record,library,completeness=proofs.get(bid),hashes=hashes)
        # External coverage declarations are bound to this precise question.
        if bid in proofs and proofs[bid].get('question_sha256')!=sig['sha256']:issues.append('coverage_signature_stale')
        signatures[bid]=sig;issues=sorted(set(issues+sig['issues']))
        if issues:sig['automatic_eligible']=False
        details[bid]=dict(bank_id=bid,source=bank['source'],source_id=saved['source_id'] if saved else None,
                         source_uid=saved['source_uid'] if saved else None,collection_id=bank['collection_id'],
                         book=meta.get('book'),locator=meta.get('locator'),
                         exam_identity=dict(year=identity['year'],math_type=identity['math_type'],number=identity['number']) if identity else None,
                         entity_id=members[bid]['entity_id'] if bid in members else None)
        buckets[('full_question_exact',sig['sha256'])].add(bid)
        if record['stem']['text'].strip():buckets[('same_stem_text',r.digest(text(record['stem']['text'])))].add(bid)
        for sha in sig['payload']['stem']['images']+sig['payload']['supplemental_stem_images']:
            if not sha.startswith('unverified:'):buckets[('shared_question_image',sha)].add(bid)
        if identity:
            if identity['math_type'] in (1,2,3) and str(identity['year']).isdigit() and identity['number']:
                buckets[('same_exam_identity',(identity['math_type'],str(identity['year']),identity['number']))].add(bid)
            if identity['sha256']:buckets[('legacy_identity_hash',identity['sha256'])].add(bid)
        # Validate the exact currently installed answer role independently.
        apath=res['answer_path'] if res else None
        aim=image(apath) if apath else None
        answers[bid]=r.digest(dict(text=text(bank['answer']),image=aim['sha256'] if aim else None)) if (bank['answer'] or apath) else None
        qpath=res['question_path'] if res else None
        qim=image(qpath) if qpath else None
        question_roles[bid]=r.digest(dict(text=bank['stem'] or '',image_sha256=qim['sha256'] if qim else None))
        # Late role failures must also block any automatic claim.
        # A current full-role human review can establish coverage for legacy
        # image questions whose options/type were not separately transcribed.
        if set(issues)-{'completeness_unproven','unknown_question_type','incomplete_options'}:invalid.add(bid)
        if bid in invalid:sig['automatic_eligible']=False
        diagnostics.append(dict(bank_id=bid,signature_sha256=sig['sha256'],automatic_eligible=sig['automatic_eligible'],issues=sorted(set(issues))))
    manual=set()
    from app.bank.identity_reviews import confirmed_pairs
    for left,right in confirmed_pairs(conn):
        if left not in details or right not in details:continue
        review=conn.execute('''SELECT * FROM bank_identity_reviews WHERE left_id=? AND right_id=? ORDER BY rowid DESC LIMIT 1''',(left,right)).fetchone()
        before=json.loads(review['before_json']);material=before.get('materials',{})
        pair=tuple(sorted((left,right)));buckets[('confirmed_review',pair)].update(pair)
        if not set(pair)&invalid and all(material.get(b,{}).get('question')==question_roles[b] for b in pair):manual.add(pair)
    for link in rows(conn,'bank_links'):
        pair=tuple(sorted((link['left_id'],link['right_id'])))
        if all(b in details for b in pair):buckets[('legacy_link',pair)].update(pair)
    grouped={}
    for (reason,_),ids in buckets.items():
        if len(ids)>1:grouped.setdefault(tuple(sorted(ids)),set()).add(reason)
    automatic=[];pending=[]
    for ids,reasons in sorted(grouped.items()):
        exact=len({r.canonical(signatures[b]['payload']) for b in ids})==1 and all(signatures[b]['automatic_eligible'] for b in ids)
        reviewed=tuple(ids) in manual
        extra=[]
        if len({answers[b] for b in ids if answers[b] is not None})>1:extra.append('answer_conflict_requires_review')
        if 'full_question_exact' in reasons and not exact:extra.append('full_question_completeness_unproven_or_invalid')
        collections=sorted({details[b]['collection_id'] for b in ids})
        item=dict(bank_ids=list(ids),sources=[details[b] for b in ids],reasons=sorted(reasons|set(extra)),
                  collection_decision_required=len(collections)>1,collections=collections)
        (automatic if (exact or reviewed) and 'answer_conflict_requires_review' not in extra else pending).append(item)
    return dict(schema='mathlens.bank-identity-preview/v1',read_only=True,
        counts=dict(source_records=len(details),singleton_members=len(members),automatic_groups=len(automatic),
                    pending_groups=len(pending),automatic_bank_ids=len({b for g in automatic for b in g['bank_ids']}),
                    pending_bank_ids=len({b for g in pending for b in g['bank_ids']})),
        automatic=automatic,pending_review=pending,signatures=diagnostics,
        limitations=['只读报告，不写实体边；组可能重叠，不表示可传递合并。',
                     '没有完整性证明的历史题面只能待核；相似数学表达不自动认定。',
                     '题面精确一致也不自动决定跨题集主归属；不同答案一律待核。'])
