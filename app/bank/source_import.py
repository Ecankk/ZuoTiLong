"""The single preview/confirm entry point for standard source records.

Preview opens only the common library in read-only mode. Import owns one
library transaction and never initializes or writes the personal workspace.
"""
from contextlib import closing, contextmanager, ExitStack
import json
from pathlib import Path
import sqlite3
import uuid

from app.bank import source_records as records
from app.bank import entities
from app.common import now_iso


@contextmanager
def library(config, *, write=False):
    path = config.library_database.resolve()
    if not path.exists() and not write:
        conn = sqlite3.connect(':memory:')
    else:
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path.as_uri() + ('?mode=rwc' if write else '?mode=ro'), uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
    finally:
        conn.close()


def _tables(conn):
    from app.storage.boundaries import schema_rows
    return {r['name'] for r in schema_rows(conn)}


def _state(conn):
    tables = _tables(conn)
    return {name: [dict(r) for r in conn.execute('SELECT * FROM ' + name + ' ORDER BY 1')]
            for name in ('bank_questions', 'bank_resources', 'bank_identity', 'bank_source_records') if name in tables}


def _identity_entries(document):
    if not document:
        return {}
    if isinstance(document, (str, Path)):
        document=json.loads(Path(document).read_text(encoding='utf8'))
    if document.get('schema') not in (None, 'mathlens.bank-identities/v1'):
        raise ValueError('Invalid identity decisions schema')
    return {entry['source_uid']: entry for entry in document.get('entries', [])}


def _source_signatures(current):
    values={};stems={};images={}
    for bid,row in current.items():
        try:
            record=json.loads(row['record_json'])
            values[bid]=entities.record_signature(record)
            stem=record.get('stem',{}).get('text','').strip()
            if stem: stems.setdefault(records.digest(stem),set()).add(bid)
            for image in record.get('stem',{}).get('images',[]):
                images.setdefault(image.get('sha256'),set()).add(bid)
        except (KeyError,TypeError,json.JSONDecodeError):
            continue
    return values,stems,images


def _entity_tables(conn):
    tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return tables >= {'question_entities','question_entity_members'} and bool(
        conn.execute('SELECT 1 FROM question_entity_members LIMIT 1').fetchone())


def preview(conn, batch, corrections, applied, excluded, collection, *, bank_ids=None, baselines=None,asset_root=None,figure_root=None,identities=None):
    from app.bank.collections import require
    require(conn,collection)
    state = _state(conn)
    current = {r['bank_id']: r for r in state.get('bank_source_records', [])}
    for bid,baseline in (baselines or {}).items():
        if bid not in current:current[bid]=dict(bank_id=bid,record_json=records.canonical(baseline),record_sha256=records.digest([baseline,[]]))
    questions = {r['id']: r for r in state.get('bank_questions', [])}
    figure_owners={}
    for row in current.values():
        prior=json.loads(row['record_json'])
        if prior['source_id']!=batch[0]['source_id'] or questions.get(row['bank_id'],{}).get('collection_id')!=collection:continue
        for e in prior.get('supplemental_figures',{}).get('entries',[]):figure_owners[e['figure_id']]=(prior['source_uid'],e['role'])
    for record in batch:
        for e in record.get('supplemental_figures',{}).get('entries',[]):
            if e['figure_id'] in figure_owners and figure_owners[e['figure_id']]!=(record['source_uid'],e['role']):raise ValueError('figure_id_conflict: '+e['figure_id'])
    exam_identities = {r['bank_id']: (str(r['year']), r['math_type'], r['number']) for r in state.get('bank_identity', [])}
    excluded_ids = {r['source_uid'] for r in excluded}
    report = dict(source_id=batch[0]['source_id'], revision=batch[0]['revision'], added=[], updated=[], unchanged=[],
                  missing_fields=[], identity_conflicts=[], duplicate_candidates=[], excluded=excluded,
                  overrides_applied=applied, errata_applied=[],invalidated_annotations=[],needs_annotation=[],metadata_only=[],collection_id=collection,collection_conflicts=[],
                  identity_matches=[],identity_pending=[],identity_actions={})
    report.update(figures_applied=[],figure_conflicts=[])
    report['figures_sha256']=records.digest(corrections['figures']) if isinstance(corrections,dict) and 'figures' in corrections else None
    content_groups = {}
    source_signatures,stem_signatures,image_signatures=_source_signatures(current)
    decision_entries=_identity_entries(identities)
    has_entities=_entity_tables(conn)
    incoming_signatures={};incoming_bids={}
    for record in batch:
        sig=entities.record_signature(record)
        incoming_signatures.setdefault(sig,[]).append(record['source_uid'])
        incoming_bids[record['source_uid']]=(bank_ids or {}).get((record['source_id'],record['source_uid']),records.bank_id(record))
    for row in current.values():
        old = json.loads(row['record_json'])
        content_groups.setdefault(records.digest([old['stem'], old['options']]), set()).add(row['bank_id'])
    for record in batch:
        if record['source_uid'] in excluded_ids:
            report['duplicate_candidates'].append(dict(bank_ids=[records.bank_id(record)],
                source_uid=record['source_uid'], reason='excluded_pending_candidate'))
            continue
        bid = (bank_ids or {}).get((record['source_id'],record['source_uid']), records.bank_id(record))
        old = current.get(bid)
        previous=json.loads(old['record_json']) if old else {}
        old_figs={e['figure_id']:e for e in previous.get('supplemental_figures',{}).get('entries',[])}
        new_figs={e['figure_id']:e for e in record.get('supplemental_figures',{}).get('entries',[])}
        for fid,e in old_figs.items():
            if fid not in new_figs:raise ValueError('figure_manifest_incomplete: '+record['source_uid']+' / '+fid)
            if new_figs[fid]['role']!=e['role']:raise ValueError('figure_id_conflict: '+fid)
        old_material=new_material=None
        if new_figs and asset_root is not None:
            from app.bank.figures import material_revision
            new_material=material_revision(record,asset_root,figure_root)
            resource=next((r for r in state.get('bank_resources',[]) if r['bank_id']==bid),None)
            if resource:
                meta=json.loads(resource['metadata_json']);materials={}
                for role,field in (('question','stem'),('analysis','explanation'),('answer','answer')):
                    path=resource[role+'_path'] or '';text=questions[bid][field] or ''
                    part=meta.get('resources',{}).get(role,{})
                    image=part.get('display_image') or next(iter(part.get('images',[])),{})
                    sha=image.get('sha256') if path else None
                    if text or sha:materials[role]=dict(text=text,path=path,image_sha256=sha,sha256=records.digest(dict(text=text,image_sha256=sha)))
                old_material=records.digest(materials)
        for fid,e in new_figs.items():
            before=old_figs.get(fid);action='added' if before is None else 'unchanged' if before==e else 'metadata_only' if before['image']['sha256']==e['image']['sha256'] else 'replaced'
            report['figures_applied'].append(dict(bank_id=bid,source_uid=record['source_uid'],figure_id=fid,role=e['role'],kind=e['kind'],caption=e['caption'],reason=e['reason'],evidence=e['evidence'],action=action,old_image_sha256=before['image']['sha256'] if before else None,new_image_sha256=e['image']['sha256'],old_material_revision=old_material,new_material_revision=new_material,annotation_invalidated=False))
        report['errata_applied'].extend(dict(bank_id=bid,**e,original_fragment=e['find'],new_fragment=e['replace']) for e in record.get('errata',[]))
        if bid in questions:
            stored=questions[bid].get('collection_id')
            if stored is None:
                from app.bank.collections import initial
                stored=initial(questions[bid],json.loads(old['record_json']) if old else None)
            if stored!=collection:report['collection_conflicts'].append(dict(bank_id=bid,existing=stored,requested=collection))
        if bid in questions and not old:
            raise ValueError('Bank ID collision with an unmanaged record: ' + bid)

        # Incremental identity detection is deliberately exact-content only.
        # Weak signals are reported as pending candidates and never published.
        signature=entities.record_signature(record)
        decision=decision_entries.get(record['source_uid'],{})
        target=decision.get('bank_id') or decision.get('target_bank_id')
        match_candidates=[]
        if target:
            match_candidates=[target]
        else:
            match_candidates=[other for other,value in source_signatures.items() if value==signature and other!=bid]
            for uid in incoming_signatures.get(signature,[]):
                candidate=incoming_bids[uid]
                if candidate!=bid and candidate not in match_candidates:match_candidates.append(candidate)
        weak=[]
        stem=record.get('stem',{}).get('text','').strip()
        if stem:
            weak.extend(sorted(stem_signatures.get(records.digest(stem),set())-{bid}))
        weak_image={sha for part in (record.get('stem',{}),) for sha in [im.get('sha256') for im in part.get('images',[])]}
        for sha in weak_image: weak.extend(sorted(image_signatures.get(sha,set())-{bid}))
        weak=sorted(set(weak))
        action='new';entity_id=None;member_state='confirmed';reason='new_source_record'
        explicit_same=decision.get('decision') in ('same','confirmed','attach') or bool(target)
        explicit_distinct=decision.get('decision') in ('distinct','separate')
        if old:
            member_row=entities.member(conn,bid) if has_entities else None;entity_id=member_row['entity_id'] if member_row else None;reason='existing_source_record'
            if has_entities and explicit_same and target:
                target_member=entities.member(conn,target)
                if target_member is None: raise ValueError('Identity target is not an existing entity member: '+str(target))
                action='same';member_state='confirmed';entity_id=target_member['entity_id'];reason='identity_decision'
                report['identity_matches'].append(dict(source_uid=record['source_uid'],bank_id=bid,target_bank_id=target,entity_id=entity_id,reason=reason))
        elif explicit_distinct:
            reason='explicit_distinct'
        elif match_candidates:
            target_member=None
            if not has_entities:
                action='pending';member_state='pending';reason='identity_tables_not_initialized'
                report['identity_pending'].append(dict(source_uid=record['source_uid'],bank_id=bid,candidate_bank_ids=match_candidates,reason=reason))
                report['identity_actions'][record['source_uid']]=dict(bank_id=bid,signature=signature,action=action,state=member_state,entity_id=None,reason=reason)
            else:
                target_member=entities.member(conn,match_candidates[0])
            if target_member is None and has_entities:
                raise ValueError('Identity target is not an existing entity member: '+str(match_candidates[0]))
            if target_member is not None:
                cross=questions.get(match_candidates[0],{}).get('collection_id')!=collection
                collection_decided=bool(decision.get('entity_collection_id') or decision.get('collection_id'))
                if cross and not collection_decided:
                    member_state='pending';reason='collection_decision_required';action='pending';entity_id=target_member['entity_id']
                    report['collection_conflicts'].append(dict(kind='identity',bank_id=bid,existing=questions.get(match_candidates[0],{}).get('collection_id'),requested=collection,existing_bank_id=match_candidates[0],suggested_priority='zhenti>first_book>other'))
                else:
                    action='same';member_state='confirmed';entity_id=target_member['entity_id'];reason='full_question_exact' if len(match_candidates)==1 else 'identity_decision'
                    report['identity_matches'].append(dict(source_uid=record['source_uid'],bank_id=bid,target_bank_id=match_candidates[0],entity_id=entity_id,reason=reason))
        elif weak:
            action='pending';member_state='pending';reason='weak_signal_requires_review'
            report['identity_pending'].append(dict(source_uid=record['source_uid'],bank_id=bid,candidate_bank_ids=weak,reason=reason))
        if action=='pending' and not any(x.get('source_uid')==record['source_uid'] for x in report['identity_pending']):
            report['identity_pending'].append(dict(source_uid=record['source_uid'],bank_id=bid,candidate_bank_ids=match_candidates or weak,reason=reason))
        if action=='same' and not any(x.get('source_uid')==record['source_uid'] for x in report['identity_matches']):
            report['identity_matches'].append(dict(source_uid=record['source_uid'],bank_id=bid,target_bank_id=match_candidates[0] if match_candidates else target,entity_id=entity_id,reason=reason))
        report['identity_actions'][record['source_uid']]=dict(bank_id=bid,signature=signature,action=action,state=member_state,entity_id=entity_id,reason=reason)
        changes = [v for v in applied if v['source_uid'] == record['source_uid']]
        sha = records.digest([record, changes])
        category = 'added' if not old else 'unchanged' if old['record_sha256'] == sha else 'updated'
        report[category].append(bid)
        from app.bank.book_numbers import number_only
        metadata_only=category=='updated' and number_only(old,record,changes)
        if metadata_only:report['metadata_only'].append(bid)
        figure_material_change=bool(new_figs and old_material!=new_material)
        if category=='updated' and old and (any(json.loads(old['record_json'])[r]!=record[r] for r in ('stem','options','answer','analysis')) or figure_material_change):
            if any(table in _tables(conn) and conn.execute('SELECT 1 FROM '+table+' WHERE bank_id=?',(bid,)).fetchone() for table in ('question_annotation_links','imported_question_annotations')):report['invalidated_annotations'].append(bid)
            if 'question_annotations' in _tables(conn):
                report['invalidated_annotations'].extend(r[0] for r in conn.execute('SELECT l.bank_id FROM question_annotation_links l JOIN question_annotations a ON a.id=l.annotation_id WHERE a.bank_id=?',(bid,)))
        figure_metadata_only=bool(old and new_figs and old_material==new_material and {k:v for k,v in previous.items() if k!='supplemental_figures'}=={k:v for k,v in record.items() if k!='supplemental_figures'})
        if figure_metadata_only and bid not in report['metadata_only']:report['metadata_only'].append(bid)
        if category in ('added', 'updated') and not metadata_only and not figure_metadata_only:
            report['needs_annotation'].append(bid)
        missing = [key for key in ('question_type', 'max_score') if record[key] is None]
        missing += [key for key in ('answer', 'analysis') if not record[key]['text'].strip() and not record[key]['images']]
        if any(record[k] is not None for k in records.IDENTITY) and not all(record[k] is not None for k in records.IDENTITY):
            missing.append('complete_exam_identity')
        if missing:
            report['missing_fields'].append(dict(bank_id=bid, source_uid=record['source_uid'], fields=missing))
        if all(record[k] is not None for k in records.IDENTITY):
            identity = (str(record['exam_year']), record['math_type'], record['number'])
            overlap = sorted(other for other, value in exam_identities.items() if value == identity and other != bid)
            if overlap:
                report['identity_conflicts'].append(dict(bank_id=bid, exam_year=record['exam_year'],
                    math_type=record['math_type'], number=record['number'], existing_or_batch_bank_ids=overlap))
            exam_identities[bid] = identity
        key = records.digest([record['stem'], record['options']])
        content_groups.setdefault(key, set()).add(bid)
        if not record['number'] and record['exam_year']:
            report['duplicate_candidates'].append(dict(bank_ids=[bid], reason='unnumbered_exam_candidate'))
    for ids in content_groups.values():
        if len(ids) > 1 and any(b in report['added'] + report['updated'] + report['unchanged'] for b in ids):
            report['duplicate_candidates'].append(dict(bank_ids=sorted(ids), reason='identical_stem_and_options'))
    report['invalidated_annotations']=sorted(set(report['invalidated_annotations']))
    for item in report['figures_applied']:item['annotation_invalidated']=item['bank_id'] in report['invalidated_annotations']
    report['plan_sha256'] = records.digest(dict(batch=batch, corrections=corrections, identities=identities, exam_identities=exam_identities, state=state, report=report))
    return report


def _copy_assets(record, asset_root, library_root,figure_root=None):
    manifest = {}
    extension = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
    for role in ('stem', 'answer', 'analysis'):
        from app.bank.figures import parts
        source_parts=parts(record,role,asset_root,figure_root)
        images = []
        for part,part_root in source_parts:
            for image in part['images']:
                data = records.asset_path(part_root, image['path']).read_bytes()
                if records.sha256(data) != image['sha256']:
                    raise ValueError('Asset changed after preview: ' + image['path'])
                relative = 'bank-assets/source/' + image['sha256'] + extension[image['media_type']]
                target = library_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if records.sha256(target.read_bytes()) != image['sha256']:
                        raise ValueError('Existing content-addressed asset is corrupt: ' + relative)
                else:
                    # Content-addressed immutable files may remain after a rollback;
                    # no row points at them until the transaction commits.
                    with target.open('xb') as output:
                        output.write(data)
                images.append(dict(image, path=relative))
        item = dict(text=records.display(record, role), images=images)
        if len(images) > 1:
            # Existing read/frozen-material contracts have one image per role.
            # Preserve originals and concatenate only the display derivative.
            from io import BytesIO
            from PIL import Image
            with ExitStack() as stack:
                originals = [stack.enter_context(Image.open(library_root / i['path'])).convert('RGB') for i in images]
                canvas = Image.new('RGB', (max(i.width for i in originals), sum(i.height for i in originals)), 'white')
                y = 0
                for image in originals:
                    canvas.paste(image, (0, y)); y += image.height
                raw = BytesIO(); canvas.save(raw, format='PNG'); data = raw.getvalue()
            sha = records.sha256(data)
            relative = 'bank-assets/source/' + sha + '.png'
            target = library_root / relative
            if target.exists() and records.sha256(target.read_bytes()) != sha:
                raise ValueError('Corrupt display derivative: ' + relative)
            if not target.exists():
                with target.open('xb') as output:output.write(data)
            item['display_image'] = dict(path=relative, sha256=sha, media_type='image/png')
        manifest['question' if role == 'stem' else role] = item
    return manifest


def _apply_entity_action(conn, report, record, bank_id):
    action=report.get('identity_actions',{}).get(record['source_uid'],{})
    signature=action.get('signature') or entities.record_signature(record)
    existing=entities.member(conn,bank_id)
    if existing is not None:
        entities.register_member(conn,bank_id,existing['entity_id'],signature,action.get('state',existing['state']))
        return existing['entity_id']
    entity_id=action.get('entity_id') if action.get('action') in ('same','pending') else None
    display_bank_id=bank_id
    collection=report['collection_id']
    if entity_id:
        target=conn.execute('SELECT display_bank_id,collection_id FROM question_entities WHERE id=?',(entity_id,)).fetchone()
        if target:
            display_bank_id=target['display_bank_id'];collection=target['collection_id']
    else:
        entity_id='entity-'+uuid.uuid4().hex
        stamp=now_iso()
        conn.execute('INSERT INTO question_entities VALUES(?,?,?,?,?)',(entity_id,display_bank_id,collection,1,stamp))
    entities.register_member(conn,bank_id,entity_id,signature,action.get('state','confirmed'))
    stamp=now_iso();request_id='import-identity:'+report['source_id']+':'+record['source_uid']+':'+report['plan_sha256']
    before=json.dumps({},ensure_ascii=False,sort_keys=True)
    after=json.dumps(dict(entity_id=entity_id,bank_id=bank_id,display_bank_id=display_bank_id,
                          collection_id=collection,state=action.get('state','confirmed')),
                     ensure_ascii=False,sort_keys=True)
    evidence=json.dumps(dict(reason=action.get('reason','new_source_record'),candidate_bank_ids=action.get('candidate_bank_ids',[])),ensure_ascii=False,sort_keys=True)
    conn.execute('''INSERT OR IGNORE INTO question_entity_events
                    VALUES(?,?,?,?,?,?,?,?,?)''',
                 ('entity-event-'+uuid.uuid4().hex,request_id,'import_identity',
                  records.digest(after),report['plan_sha256'],before,after,evidence,stamp))
    return entity_id


def _apply(conn, config, batch, report, asset_root, *, bank_ids=None, initialize_schema=True,figure_root=None,entity_enabled=None):
    if entity_enabled is None:
        entity_enabled=_entity_tables(conn)
    if initialize_schema:
        from app.storage.boundaries import LIBRARY_TABLES
        from app.storage.split import template, copy_schema
        with closing(template()) as schema:
            copy_schema(schema, conn, LIBRARY_TABLES)
        from app.storage.library_identity import initialize
        initialize(conn)
        from app.bank.collections import initialize as collections
        collections(conn)
        from app.bank.applicability import initialize as applicability
        applicability(conn)
        from app.storage.navigation_index import initialize as navigation
        navigation(conn)
        if entity_enabled:
            entities.initialize(conn)
    excluded = {r['source_uid'] for r in report['excluded']}
    for record in batch:
        bid = (bank_ids or {}).get((record['source_id'],record['source_uid']), records.bank_id(record))
        action=report.get('identity_actions',{}).get(record['source_uid'],{})
        if record['source_uid'] in excluded:
            continue
        if bid in report['unchanged']:
            if entity_enabled and action.get('action') in ('same','pending'):
                _apply_entity_action(conn, report, record, bid)
            continue
        if bid in report.get('metadata_only',[]):
            old=conn.execute('SELECT metadata_json FROM bank_resources WHERE bank_id=?',(bid,)).fetchone()
            metadata=json.loads(old[0])
            if 'supplemental_figures' in record:
                from copy import deepcopy
                value=deepcopy(record['supplemental_figures'])
                for e in value['entries']:
                    image=e['image'];ext={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[image['media_type']]
                    image['path']='bank-assets/source/'+image['sha256']+ext
                    if records.sha256((config.library_dir/image['path']).read_bytes())!=image['sha256']:raise ValueError('Corrupt figure asset')
                metadata['supplemental_figures']=value
            else:metadata['book']={**metadata.get('book',{}),'number':record['book']['number']}
            changes=[v for v in report['overrides_applied'] if v['source_uid']==record['source_uid']]
            sha=records.digest([record,changes]);text=records.canonical(record);audit=records.canonical(changes)
            conn.execute('UPDATE bank_resources SET metadata_json=? WHERE bank_id=?',(records.canonical(metadata),bid))
            conn.execute('UPDATE bank_source_records SET record_json=?,record_sha256=?,overrides_json=? WHERE bank_id=?',(text,sha,audit,bid))
            conn.execute('INSERT OR IGNORE INTO bank_source_versions VALUES(?,?,?,?,?)',(bid,sha,text,audit,now_iso()))
            continue
        manifest = _copy_assets(record, asset_root, config.library_dir,figure_root)
        metadata = {k: record[k] for k in ('schema', 'source_id', 'revision', 'source_uid', *records.METADATA)}
        metadata.update(locator=record['locator'], original_source=record['original']['source_text'], resources=manifest)
        if 'book' in record:metadata['book']=record['book']
        if 'errata' in record:metadata['errata']=record['errata']
        if 'supplemental_figures' in record:
            from copy import deepcopy
            value=deepcopy(record['supplemental_figures'])
            for e in value['entries']:
                image=e['image'];raw=records.asset_path(figure_root or asset_root,image['path']).read_bytes()
                if records.sha256(raw)!=image['sha256']:raise ValueError('figure_hash_mismatch: '+e['figure_id'])
                ext={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[image['media_type']]
                path='bank-assets/source/'+image['sha256']+ext;target=config.library_dir/path
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists() and records.sha256(target.read_bytes())!=image['sha256']:raise ValueError('Corrupt figure asset')
                if not target.exists():target.write_bytes(raw)
                image['path']=path
            metadata['supplemental_figures']=value
        changes = [v for v in report['overrides_applied'] if v['source_uid'] == record['source_uid']]
        sha = records.digest([record, changes])
        conn.execute('''INSERT INTO bank_questions(id,source,source_ref,stem,answer,explanation,tags_json,created_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET source=excluded.source,source_ref=excluded.source_ref,
            stem=excluded.stem,answer=excluded.answer,explanation=excluded.explanation,tags_json=excluded.tags_json''',
            (bid, record['source_id'], record['source_uid'], manifest['question']['text'], manifest['answer']['text'],
             manifest['analysis']['text'], records.canonical(record['tags']), now_iso()))
        conn.execute('UPDATE bank_questions SET collection_id=? WHERE id=?',(report['collection_id'],bid))
        conn.execute('UPDATE bank_questions SET math_types_json=? WHERE id=?',(records.canonical(record.get('math_types',[record['math_type']] if record['math_type'] in (1,2,3) else [])),bid))
        paths = [manifest[r].get('display_image', manifest[r]['images'][0])['path'] if manifest[r]['images'] else ''
                 for r in ('question', 'analysis', 'answer')]
        conn.execute('''INSERT INTO bank_resources VALUES(?,?,?,?,?) ON CONFLICT(bank_id) DO UPDATE SET
            metadata_json=excluded.metadata_json,question_path=excluded.question_path,
            analysis_path=excluded.analysis_path,answer_path=excluded.answer_path''', (bid, records.canonical(metadata), *paths))
        # Keep known year/category for whole-paper protection even without a
        # number; only complete triples participate in exact exam matching.
        identity = (record['math_type'] or 0, str(record['exam_year']) if record['exam_year'] else '', record['number'] or 0)
        conn.execute('''INSERT INTO bank_identity VALUES(?,?,?,?,NULL) ON CONFLICT(bank_id) DO UPDATE SET
            math_type=excluded.math_type,year=excluded.year,number=excluded.number,sha256=NULL''', (bid, *identity))
        conn.execute('''INSERT INTO bank_source_records VALUES(?,?,?,?,?,?,?) ON CONFLICT(bank_id) DO UPDATE SET
            revision=excluded.revision,record_sha256=excluded.record_sha256,record_json=excluded.record_json,
            overrides_json=excluded.overrides_json''',
            (bid, record['source_id'], record['source_uid'], record['revision'], sha, records.canonical(record), records.canonical(changes)))
        conn.execute('INSERT OR IGNORE INTO bank_source_versions VALUES(?,?,?,?,?)',
                     (bid, sha, records.canonical(record), records.canonical(changes), now_iso()))
        if entity_enabled:
            _apply_entity_action(conn, report, record, bid)


def import_source(config, source_id, input_path, *, collection, asset_root=None, overrides=None, errata=None, confirm=None,figures=None,figure_root=None,identities=None):
    asset_root = Path(asset_root or Path(input_path).parent)
    batch, corrections, applied, excluded = records.load(input_path, source_id, asset_root, overrides,errata)
    if figure_root and not figures:raise ValueError('--figure-root requires --figures')
    figure_root=Path(figure_root or Path(figures).parent) if figures else None
    if figures:
        from app.bank.figures import apply
        if any('supplemental_figures' in record for record in batch):raise ValueError('figure_id_conflict: 不混用内嵌补图与外部清单')
        document=apply(batch,figures,figure_root,collection);corrections={'prior':corrections,'figures':document}
    identity_document=identities
    if identities:
        identity_document=json.loads(Path(identities).read_text(encoding='utf8')) if isinstance(identities,(str,Path)) else identities
    with library(config) as conn:
        conn.execute('BEGIN')
        report = preview(conn, batch, corrections, applied, excluded,collection,asset_root=asset_root,figure_root=figure_root,identities=identity_document)
    if confirm is None:
        return dict(report, applied=False)
    if confirm != report['plan_sha256']:
        raise ValueError('Preview changed; rerun --dry-run and confirm the new plan_sha256')
    if any(item.get('kind') != 'identity' for item in report['collection_conflicts']):
        raise ValueError('Collection conflict: existing questions cannot change collection')
    with library(config, write=True) as conn:
        entity_enabled=_entity_tables(conn)
        conn.execute('BEGIN IMMEDIATE')
        try:
            locked = preview(conn, batch, corrections, applied, excluded,collection,asset_root=asset_root,figure_root=figure_root,identities=identity_document)
            if locked['plan_sha256'] != confirm:
                raise ValueError('Library changed after preview; rerun --dry-run')
            _apply(conn, config, batch, report, asset_root,figure_root=figure_root,entity_enabled=entity_enabled)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return dict(report, applied=True)
