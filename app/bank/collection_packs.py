"""Portable collection data with hash validation and explicit maintenance writes."""
from contextlib import contextmanager,closing
from copy import deepcopy
import hashlib,json,re,sqlite3,tempfile,zipfile
from pathlib import Path
from app.bank import source_records as records,annotations,annotation_packages
from app.knowledge import catalog,packages as catalogs
from app.common import now_iso
from app.storage.boundaries import LIBRARY_TABLES,material_path

FORMAT='mathlens.collection-pack/v2'
LEGACY_FORMAT='mathlens.collection-pack/v1'
MAX_BYTES=2*1024**3
class PackTooLarge(ValueError):pass

def _schema(config):
    from app.storage.split import template,copy_schema
    from app.storage.library_identity import initialize
    from app.bank.collections import initialize as collections
    from app.storage.navigation_index import initialize as navigation
    config.library_dir.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(config.library_database)) as conn,conn,closing(template()) as source:
        conn.row_factory=sqlite3.Row;copy_schema(source,conn,LIBRARY_TABLES)
        collections(conn);initialize(conn);navigation(conn)

@contextmanager
def connection(config,write=False):
    conn=sqlite3.connect(':memory:',isolation_level=None,uri=True);conn.row_factory=sqlite3.Row
    try:
        if config.library_database.is_file():
            conn.execute('ATTACH DATABASE ? AS library',(config.library_database.resolve().as_uri()+('?mode=rw' if write else '?mode=ro'),))
        else:
            from app.storage.split import template,copy_schema
            with closing(template()) as source:copy_schema(source,conn,LIBRARY_TABLES)
            from app.bank.collections import initialize
            initialize(conn)
        yield conn
    finally:conn.close()

def _version(conn):
    if not conn.execute('SELECT 1 FROM bank_questions LIMIT 1').fetchone():return None
    return dict(conn.execute('SELECT library_id,revision FROM library_state').fetchone())

def _asset(path,assets):
    raw=path.read_bytes();sha=records.sha256(raw);suffix=path.suffix.lower()
    mime={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}.get(suffix)
    if not mime:raise ValueError('不支持的题集图片格式：'+suffix)
    name='assets/'+sha+('.jpg' if mime=='image/jpeg' else suffix);assets[name]=path
    return dict(path=name,sha256=sha,media_type=mime)

def _export_record(conn,config,row,assets,*,read_view=None):
    bid=row['id'];resource=conn.execute('SELECT * FROM bank_resources WHERE bank_id=?',(bid,)).fetchone()
    metadata=json.loads(resource['metadata_json']) if resource else {}
    saved=conn.execute('SELECT record_json FROM bank_source_records WHERE bank_id=?',(bid,)).fetchone()
    identity=dict(conn.execute('SELECT math_type,year,number,sha256 FROM bank_identity WHERE bank_id=?',(bid,)).fetchone())
    if saved:record=deepcopy(json.loads(saved[0]))
    else:
        from app.bank.exam_identity import metadata as question_metadata
        meta=question_metadata(conn,bid);kind={'选择题':'choice','填空题':'fill','解答题':'proof'}.get(meta['question_type'])
        source='S01' if row['source'] in ('数学一真题图片库','数学二真题图片库','数学三真题图片库') or metadata.get('source_url','').endswith('kaoyanshuxue') else 'S00'
        original=dict(source=row['source'],source_ref=row['source_ref'],bank_id=bid,source_url=metadata.get('source_url'))
        record=dict(schema=records.SCHEMA,source_id=source,revision='legacy-db-export/v1',source_uid=bid,
            locator=dict(path='legacy-bank/'+bid,pointer='/',source_sha256=records.digest(original)),
            exam_year=int(identity['year']) if str(identity['year']).isdigit() else None,math_type=identity['math_type'] or None,
            number=identity['number'] or None,question_type=kind,max_score=meta['max_score'],
            stem=records.resource(),answer=records.resource(),analysis=records.resource(),options=[],
            original=dict(source_text=row['source'],record=original,sha256=records.digest(original)),tags=json.loads(row['tags_json'] or '[]'))
    option_text=deepcopy(record['options']);original_stem=record['stem']['text']
    keep_options=bool(option_text) and records.display(record,'stem')==(row['stem'] or '')
    # Package the exact displayed images, including composites, so receiving
    # Pillow versions cannot change hashes used by the shared annotation index.
    for role,column,path_column in (('stem','stem','question_path'),('answer','answer','answer_path'),('analysis','explanation','analysis_path')):
        path=resource[path_column] if resource else None
        images=[_asset(material_path(config.data,path),assets)] if path else []
        text=row[column] or ''
        record[role]=records.resource(text,images)
    record['options']=[]
    if keep_options:
        record['stem']['text']=original_stem;record['stem']['sha256']=records.sha256(original_stem.encode('utf8'))
        for option in option_text:option['content']['images']=[]
        record['options']=option_text
    record['math_types']=json.loads(row['math_types_json']);record['errata']=metadata.get('errata',[])
    if metadata.get('supplemental_figures'):
        record['supplemental_figures']=deepcopy(metadata['supplemental_figures'])
        value=record['supplemental_figures']
        for e in value['entries']:e['image']=_asset(material_path(config.data,e['image']['path']),assets)
        value['materialized_roles']=sorted({e['role'] for e in value['entries']})
    current=annotations.current(conn,config.data,bid,read_view=read_view)
    pending=metadata.get('annotation_status')
    status=current['analysis']['status'] if current else pending if pending in ('needs_review','needs_catalog') else 'unannotated'
    return dict(bank_id=bid,record=record,identity=identity,annotation_status=status,errata=record['errata'])

def export_collection(config,collection,output):
    assets={};items=[]
    with connection(config) as conn:
        conn.execute('BEGIN')
        from app.bank.annotation_view import AnnotationReadView
        view=AnnotationReadView(conn,config.data)
        group=conn.execute('SELECT * FROM bank_collections WHERE id=?',(collection,)).fetchone()
        if not group:raise ValueError('题集不存在')
        for row in conn.execute('SELECT * FROM bank_questions WHERE collection_id=? ORDER BY id',(collection,)):
            items.append(_export_record(conn,config,row,assets,read_view=view))
        if not items:raise ValueError('不能导出空题集')
        counts={k:sum(r['annotation_status']==k for r in items) for k in ('ready','needs_review','needs_catalog','unannotated')};counts['total']=len(items)
        index=annotation_packages.export_package(conn,config.data,collection,read_view=view) if counts['ready'] else None
        knowledge=catalogs.export_package(conn) if catalog.active_id(conn) else None
        if index and not knowledge:raise ValueError('就绪索引缺少可导出目录')
        entity_rows=[]
        from app.bank.entities import presentation
        for item in items:
            value=presentation(conn,item['bank_id'])
            if value:entity_rows.append(value)
        files={'records.jsonl':('\n'.join(records.canonical(r) for r in items)+'\n').encode(),
               'errata.json':records.canonical([dict(bank_id=r['bank_id'],entries=r['errata']) for r in items if r['errata']]).encode()}
        if entity_rows:files['entities.json']=records.canonical({'schema':'mathlens.question-entities/v1','entities':entity_rows}).encode()
        if index:files['annotations.json']=records.canonical(index).encode()
        if knowledge:files['catalog.json']=records.canonical(knowledge).encode()
        sources={}
        for r in items:sources.setdefault((r['record']['source_id'],r['record']['revision']),[]).append(r['record'])
        hashes={name:records.sha256(data) for name,data in files.items()}
        hashes.update({name:records.sha256(path.read_bytes()) for name,path in assets.items()})
        manifest=dict(schema=FORMAT,collection=dict(group),created_at=now_iso(),
            version=records.digest(hashes),sources=[dict(source_id=k[0],revision=k[1],input_sha256=records.digest(v)) for k,v in sorted(sources.items())],
            catalog=dict(release_id=catalog.active_id(conn),document_sha256=knowledge['document_sha256'],package_sha256=knowledge['sha256']) if knowledge else None,
            counts=counts,files=hashes,identity_format='mathlens.question-identity-signature/v1',
            entity_count=len({e['entity_id'] for e in entity_rows}),source_record_count=len(items))
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent,suffix='.zip',delete=False) as stream:temporary=Path(stream.name)
    try:
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',records.canonical(manifest))
            for name,data in files.items():archive.writestr(name,data)
            for name,path in assets.items():archive.write(path,name)
        temporary.replace(output)
    finally:temporary.unlink(missing_ok=True)
    return dict(path=str(output),bytes=output.stat().st_size,manifest=manifest)

@contextmanager
def unpack(path):
    with tempfile.TemporaryDirectory(prefix='mathlens-collection-') as folder,zipfile.ZipFile(path) as archive:
        root=Path(folder);names=archive.namelist()
        if len(names)!=len(set(names)):raise ValueError('题集包重复条目')
        if len(names)>30000 or sum(i.file_size for i in archive.infolist())>MAX_BYTES:raise PackTooLarge('题集包过大或文件过多')
        if 'manifest.json' not in names:raise ValueError('缺少manifest.json')
        if archive.getinfo('manifest.json').file_size>2*1024**2:raise PackTooLarge('manifest过大')
        manifest=json.loads(archive.read('manifest.json'))
        if not isinstance(manifest,dict):raise ValueError('manifest字段不合法')
        required={'schema','collection','version','created_at','sources','catalog','counts','files'}
        if manifest.get('schema')==FORMAT:
            required |= {'identity_format','entity_count','source_record_count'}
        if set(manifest) != required or manifest['schema'] not in (FORMAT,LEGACY_FORMAT):raise ValueError('manifest字段不合法')
        group=manifest['collection']
        if (not isinstance(group,dict) or set(group)!={'id','name','kind','sort_order'} or not re.fullmatch('[a-z][a-z0-9-]{0,63}',group['id'])
            or group['kind'] not in ('exam','book','other','example') or not isinstance(group['name'],str) or not group['name'].strip() or type(group['sort_order']) is not int):raise ValueError('题集登记字段不合法')
        if not isinstance(manifest['files'],dict) or manifest['version']!=records.digest(manifest['files']):raise ValueError('题集版本/文件摘要不合法')
        if set(names)!={'manifest.json',*manifest.get('files',{})}:raise ValueError('题集包版本/文件清单不匹配')
        for name in names:
            target=records.asset_path(root,name)
            if name!='manifest.json' and not (name in ('records.jsonl','annotations.json','catalog.json','errata.json','entities.json') or re.fullmatch(r'assets/[0-9a-f]{64}\.(png|jpg|webp)',name)):raise ValueError('题集包含非数据文件')
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(name) as source,target.open('wb') as output:
                sha=hashlib.sha256()
                while chunk:=source.read(1024*1024):sha.update(chunk);output.write(chunk)
            if name!='manifest.json' and sha.hexdigest()!=manifest['files'][name]:raise ValueError('题集文件SHA256不匹配：'+name)
        items=[json.loads(line) for line in (root/'records.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
        seen=set();source_uids=set()
        for item in items:
            if not isinstance(item,dict) or set(item)!={'bank_id','record','identity','annotation_status','errata'}:raise ValueError('题集记录封装字段不合法')
            bid=item['bank_id']
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,179}',bid) or bid in seen:raise ValueError('题目ID非法或重复')
            seen.add(bid)
            from jsonschema import ValidationError
            try:records.validate(item['record'],root)
            except ValidationError as exc:raise ValueError('标准题目格式错误：'+exc.message) from exc
            pair=(item['record']['source_id'],item['record']['source_uid'])
            if pair in source_uids:raise ValueError('同一来源UID重复')
            source_uids.add(pair)
            identity=item['identity'];record=item['record']
            if (not isinstance(identity,dict) or set(identity)!={'math_type','year','number','sha256'}
                or (identity['math_type'] or None)!=record['math_type'] or (identity['number'] or None)!=record['number']
                or (str(record['exam_year']) if record['exam_year'] else '')!=str(identity['year'] or '')
                or identity['sha256'] is not None and not re.fullmatch('[0-9a-f]{64}',identity['sha256'])):raise ValueError('题集身份与标准记录不一致')
            if item['errata']!=item['record'].get('errata',[]):raise ValueError('勘误清单不匹配')
            if item['annotation_status'] not in ('ready','needs_review','needs_catalog','unannotated'):raise ValueError('来源标注状态不合法')
        counts={k:sum(i['annotation_status']==k for i in items) for k in ('ready','needs_review','needs_catalog','unannotated')};counts['total']=len(items)
        if counts!=manifest['counts'] or not items or any(type(v) is not int for v in manifest['counts'].values()):raise ValueError('题集题数/状态统计不匹配')
        sources={}
        for item in items:sources.setdefault((item['record']['source_id'],item['record']['revision']),[]).append(item['record'])
        expected=[dict(source_id=k[0],revision=k[1],input_sha256=records.digest(v)) for k,v in sorted(sources.items())]
        if manifest['sources']!=expected:raise ValueError('来源清单与标准记录不一致')
        errata=json.loads((root/'errata.json').read_text(encoding='utf8'))
        if errata!=[dict(bank_id=r['bank_id'],entries=r['errata']) for r in items if r['errata']]:raise ValueError('勘误文件与记录不一致')
        index=json.loads((root/'annotations.json').read_text(encoding='utf8')) if 'annotations.json' in names else None
        knowledge=json.loads((root/'catalog.json').read_text(encoding='utf8')) if 'catalog.json' in names else None
        if index:annotation_packages.validate_package(index)
        if knowledge:catalogs.validate_package(knowledge)
        if bool(manifest['catalog'])!=bool(knowledge) or knowledge and manifest['catalog']['package_sha256']!=knowledge['sha256']:raise ValueError('目录清单不匹配')
        if counts['ready'] and (not index or not knowledge):raise ValueError('就绪题缺少标注索引或目录')
        ready_materials=[]
        for item in items:
            if item['annotation_status']!='ready':continue
            roles={}
            for role,key in (('question','stem'),('answer','answer'),('analysis','analysis')):
                part=item['record'][key]
                if part['text'] or part['images']:roles[role]=records.digest(dict(text=records.display(item['record'],key),image_sha256=part['images'][0]['sha256'] if part['images'] else None))
            if not any(e['role_hashes']==roles for e in index['entries']):raise ValueError('就绪题的材料版本没有对应索引：'+item['bank_id'])
            ready_materials.append(roles)
        if index and any(e['collection_id']!=group['id'] or e['role_hashes'] not in ready_materials for e in index['entries']):raise ValueError('索引包含其他题集或未包含的材料')
        yield root,manifest,items,index,knowledge

def catalog_plan(conn,knowledge):
    current=catalog.document(conn)
    if not knowledge:return dict(status='current',current_release_id=catalog.active_id(conn),required_release_id=None)
    incoming={n['id']:n for n in knowledge['document']['nodes']};old={n['id']:n for n in current['document']['nodes']} if current else {}
    fields=annotations.DEPENDENCY_FIELDS
    changed=[key for key in old.keys()&incoming.keys() if any(old[key].get(f)!=incoming[key].get(f) for f in fields)]
    status='conflict' if changed or old.keys()-incoming.keys() and incoming.keys()-old.keys() else 'keep_current' if incoming.keys()<=old.keys() else 'upgrade'
    if current and current['document']==knowledge['document']:status='current'
    return dict(status=status,current_release_id=catalog.active_id(conn),required_release_id='catalog-'+knowledge['document_sha256'],conflicting_nodes=changed)

def preview(conn,config,manifest,items,index,knowledge):
    collection=manifest['collection'];report=dict(collection=collection,counts=manifest['counts'],added=[],updated=[],unchanged=[],collection_conflicts=[],catalog=catalog_plan(conn,knowledge),annotation_summary=dict(entries=len(index['entries']) if index else 0),applied=False)
    report.update(package_version=manifest['version'],created_at=manifest['created_at'],sources=manifest['sources'],
                  trust_notice='确认表示接受该题集及所附目录、共享索引来源；散列只能校验一致性，不认证发布者或数学正确性。')
    existing=conn.execute('SELECT kind FROM bank_collections WHERE id=?',(collection['id'],)).fetchone()
    if existing and existing['kind']!=collection['kind']:report['collection_conflicts'].append(dict(collection_id=collection['id'],existing_kind=existing['kind'],requested_kind=collection['kind']))
    for item in items:
        bid=item['bank_id'];old=conn.execute('SELECT * FROM bank_questions WHERE id=?',(bid,)).fetchone()
        if old and old['collection_id']!=collection['id']:report['collection_conflicts'].append(dict(bank_id=bid,existing=old['collection_id'],requested=collection['id']))
        same=False
        if old:
            try:
                actual=annotations.materials(conn,config.data,bid);expected={}
                for role,key in (('question','stem'),('answer','answer'),('analysis','analysis')):
                    part=item['record'][key]
                    if part['text'] or part['images']:expected[role]=records.digest(dict(text=records.display(item['record'],key),image_sha256=part['images'][0]['sha256'] if part['images'] else None))
                meta=conn.execute('SELECT metadata_json FROM bank_resources WHERE bank_id=?',(bid,)).fetchone();meta=json.loads(meta[0]) if meta else {}
                from app.bank.exam_identity import metadata as exam_metadata
                normalized=exam_metadata(conn,bid);kind={'选择题':'choice','填空题':'fill','解答题':'proof'}.get(normalized['question_type'])
                same=(annotation_packages.role_hashes(actual)==expected and kind==item['record']['question_type'] and normalized['max_score']==item['record']['max_score']
                      and meta.get('supplemental_figures',{}).get('entries',[])==[{**e,'image':{**e['image'],'path':'bank-assets/source/'+e['image']['sha256']+{'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[e['image']['media_type']]}} for e in item['record'].get('supplemental_figures',{}).get('entries',[])]
                      and meta.get('book')==item['record'].get('book') and meta.get('errata',[])==item['record'].get('errata',[])
                      and json.loads(old['math_types_json'])==item['record'].get('math_types',[]))
            except ValueError:same=False
        report['unchanged' if same else 'updated' if old else 'added'].append(bid)
    report['plan_sha256']=records.digest(dict(manifest=manifest,state=_version(conn),report=report))
    return report

def import_collection(config,path,confirm=None):
    with Path(path).open('rb') as source:package_sha256=hashlib.file_digest(source,'sha256').hexdigest()
    with unpack(path) as (root,manifest,items,index,knowledge):
        entity_package=json.loads((root/'entities.json').read_text(encoding='utf8')) if 'entities.json' in manifest.get('files',{}) else None
        with connection(config) as conn:
            conn.execute('BEGIN');report=preview(conn,config,manifest,items,index,knowledge)
        report['package_sha256']=package_sha256
        if confirm is None:return report
        if confirm!=report['plan_sha256']:raise ValueError('预演已过期，请重新预演')
        if report['collection_conflicts'] or report['catalog']['status']=='conflict':raise ValueError('题集/目录冲突，不能确认导入')
        from app.storage.library_backup import backup_library
        existed=config.library_database.is_file()
        if existed:backup=backup_library(config.library_dir,workspaces=(config.data,))
        _schema(config)
        if not existed:backup=backup_library(config.library_dir,workspaces=(config.data,))
        with connection(config,True) as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                locked=preview(conn,config,manifest,items,index,knowledge)
                if locked['plan_sha256']!=confirm:raise ValueError('备份期间题库发生变化，请重新预演')
                c=manifest['collection'];conn.execute('INSERT OR IGNORE INTO bank_collections VALUES(?,?,?,?)',(c['id'],c['name'],c['kind'],c['sort_order']))
                if report['catalog']['status']=='upgrade':catalogs.import_package(conn,knowledge,trusted_sha256=knowledge['sha256'],expected_parent=catalog.active_id(conn),confirmed=True)
                from app.bank.source_import import _apply
                from app.bank import entities
                entities.initialize(conn)
                batch=[i['record'] for i in items];ids={(i['record']['source_id'],i['record']['source_uid']):i['bank_id'] for i in items}
                _apply(conn,config,batch,dict(unchanged=report['unchanged'],excluded=[],overrides_applied=[],collection_id=c['id'],plan_sha256=report['plan_sha256']),root,bank_ids=ids,initialize_schema=False,entity_enabled=True)
                if entity_package and entity_package.get('schema')=='mathlens.question-entities/v1':
                    for entity in entity_package.get('entities',[]):
                        eid=entity.get('entity_id');display=entity.get('display_bank_id');
                        if not eid or not display:continue
                        target=conn.execute('SELECT collection_id FROM bank_questions WHERE id=?',(display,)).fetchone()
                        if not target:continue
                        conn.execute('INSERT OR IGNORE INTO question_entities VALUES(?,?,?,?,?)',(eid,display,target[0],1,now_iso()))
                        for source in entity.get('sources',[]):
                            sbid=source.get('bank_id')
                            if conn.execute('SELECT 1 FROM bank_questions WHERE id=?',(sbid,)).fetchone():
                                conn.execute('UPDATE question_entity_members SET entity_id=?,state=\'confirmed\' WHERE bank_id=?',(eid,sbid))
                for item in items:
                    if item['bank_id'] in report['unchanged']:continue
                    conn.execute('UPDATE bank_identity SET sha256=? WHERE bank_id=?',(item['identity']['sha256'],item['bank_id']))
                    row=conn.execute('SELECT metadata_json FROM bank_resources WHERE bank_id=?',(item['bank_id'],)).fetchone();meta=json.loads(row[0]);meta['annotation_status']=item['annotation_status']
                    conn.execute('UPDATE bank_resources SET metadata_json=? WHERE bank_id=?',(records.canonical(meta),item['bank_id']))
                if index:
                    planned=annotation_packages.preview(conn,config.data,index,c['id'])
                    if planned['matches']:
                        annotation_packages.import_package(conn,config.data,index,trusted_sha256=index['sha256'],expected_preview_sha256=planned['preview_sha256'],confirmed=True,collection=c['id'])
                    from app.bank.annotation_view import AnnotationReadView
                    view=AnnotationReadView(conn,config.data)
                    for item in items:
                        if item['annotation_status']=='ready':
                            current=annotations.current(conn,config.data,item['bank_id'],read_view=view)
                            if not current or current['analysis']['status']!='ready':raise ValueError('题集索引未能就绪，事务已回滚：'+item['bank_id'])
                conn.commit()
            except BaseException:conn.rollback();raise
    return dict(report,applied=True,backup=backup)
