"""Build a clean, referenced-only mathlens.library-seed/v1 directory."""
from contextlib import closing
import argparse, hashlib, json, re, shutil, sqlite3, tempfile
from pathlib import Path

SCHEMA = 'mathlens.library-seed/v1'

def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def _json_strings(value):
    if isinstance(value, dict):
        for item in value.values(): yield from _json_strings(item)
    elif isinstance(value, list):
        for item in value: yield from _json_strings(item)
    elif isinstance(value, str): yield value

def _path_candidates(value):
    value = value.replace('\\', '/')
    for marker in ('bank-assets/', 'knowledge-sources/'):
        start = 0
        while True:
            index = value.find(marker, start)
            if index < 0: break
            candidate = re.split(r"[\s\"'<>)}\],;]", value[index:], 1)[0]
            yield candidate
            start = index + len(marker)

def _sidecars(path):
    return [str(p) for p in (path.with_name(path.name+'-wal'), path.with_name(path.name+'-shm'), path.with_name(path.name+'-journal')) if p.exists()]

def _ready(conn, tables):
    latest = {}
    if {'question_annotation_links','question_annotations','prepared_annotation_ids'} <= tables:
        for bid, status, order in conn.execute('''SELECT l.bank_id,json_extract(a.payload_json,'$.status'),p.rowid
            FROM question_annotation_links l JOIN question_annotations a ON a.id=l.annotation_id
            JOIN prepared_annotation_ids p ON p.id=a.id'''):
            if bid not in latest or latest[bid][0] < order: latest[bid] = (order, status)
    if {'imported_question_annotations','annotation_cache_state','prepared_annotation_ids'} <= tables:
        for bid, order in conn.execute('''SELECT a.bank_id,p.rowid FROM imported_question_annotations a
            JOIN annotation_cache_state s ON s.package_sha256=a.package_sha256 AND s.enabled=1
            JOIN prepared_annotation_ids p ON p.id=a.id'''):
            if bid not in latest or latest[bid][0] < order: latest[bid] = (order, 'ready')
    return {bid for bid, (_, status) in latest.items() if status == 'ready'}

def _scan_source(source):
    source = Path(source).resolve(); db = source/'library.db'
    if not db.is_file(): raise ValueError('library.db不存在')
    if (sidecars := _sidecars(db)): raise ValueError('源库存在未封存的SQLite sidecar/WAL：' + ', '.join(sidecars))
    from app.storage.boundaries import LIBRARY_TABLES
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row; conn.execute('PRAGMA query_only=ON')
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        refs=set()
        for table in sorted(LIBRARY_TABLES & tables):
            for row in conn.execute('SELECT * FROM "'+table+'"'):
                for value in row:
                    if not isinstance(value, str): continue
                    values = [value]
                    if value[:1] in '[{':
                        try: values = list(_json_strings(json.loads(value)))
                        except json.JSONDecodeError: pass
                    for item in values:
                        refs.update(_path_candidates(item))
        if 'knowledge_source_entries' in tables:
            for version, payload in conn.execute('SELECT source_version_id,payload_json FROM knowledge_source_entries'):
                try: parsed=json.loads(payload)
                except json.JSONDecodeError: continue
                entries=parsed.get('references', parsed.get('record',{}).get('references',[])) if isinstance(parsed,dict) else []
                for ref in entries:
                    if isinstance(ref,dict) and isinstance(ref.get('path'),str):
                        refs.add('knowledge-sources/'+version+'/'+ref['path'].replace('\\','/'))
        valid=set();missing=[]
        for rel in sorted(refs):
            if not re.fullmatch(r'(?:bank-assets|knowledge-sources)/[^/]+(?:/[^/]+)*', rel):
                missing.append({'path':rel,'reason':'invalid_relative_reference'}); continue
            path=(source/rel).resolve()
            if not path.is_relative_to(source) or not path.is_file(): missing.append({'path':rel,'reason':'missing_or_escape'}); continue
            valid.add(rel)
        identity=conn.execute('SELECT library_id,revision FROM library_state WHERE singleton=1').fetchone()
        if not identity: raise ValueError('library_state标识缺失')
        total=conn.execute('SELECT count(*) FROM bank_questions').fetchone()[0]
        ready=_ready(conn,tables)
        collections=[]
        for cid,total_count in conn.execute('SELECT collection_id,count(*) FROM bank_questions GROUP BY collection_id'):
            count=conn.execute('SELECT count(*) FROM bank_questions WHERE id IN ('+','.join('?' for _ in ready)+') AND collection_id=?',(*ready,cid)).fetchone()[0] if ready else 0
            collections.append({'id':cid,'total':total_count,'ready':count})
        return dict(tables=sorted(tables), extra_tables=sorted(tables-LIBRARY_TABLES), references=sorted(valid), missing=missing,
                    questions=total, ready=len(ready), collections=collections, library_id=identity[0], revision=identity[1])

def _unreferenced(source, refs):
    result=[]
    for root_name in ('bank-assets','knowledge-sources'):
        root=Path(source)/root_name
        if not root.exists(): continue
        for path in root.rglob('*'):
            if path.is_file() and not path.is_symlink():
                rel=path.relative_to(source).as_posix()
                if rel not in refs: result.append((rel,path.stat().st_size))
    return result

def build(source, output, release_id, *, report_path=None, force=False):
    source=Path(source).resolve(); output=Path(output).resolve(); report_path=Path(report_path).resolve() if report_path else output.with_name(output.name+'.report.json')
    if output.exists() and not force: raise ValueError('输出目录已存在；使用--force后才允许替换')
    info=_scan_source(source); unused=_unreferenced(source,set(info['references']))
    report=dict(schema='mathlens.library-seed-build-report/v1',source=str(source),output=str(output),release_id=release_id,
                source_tables=info['tables'],unlisted_tables=info['extra_tables'],missing_references=info['missing'],
                referenced_file_count=len(info['references']),unreferenced_file_count=len(unused),unreferenced_bytes=sum(s for _,s in unused),
                unreferenced_files=[dict(path=p,size=s) for p,s in unused],output_published=False)
    report_path.parent.mkdir(parents=True,exist_ok=True); report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    if info['extra_tables']: raise ValueError('源库包含未列入发行白名单的表，详见报告：'+', '.join(info['extra_tables']))
    if info['missing']: raise ValueError('源库存在缺失或越界资源引用，详见报告')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',release_id): raise ValueError('release_id格式不合法')
    from app.version import VERSION
    manifest=dict(schema=SCHEMA,release_id=release_id,min_app_version=VERSION,library_id=info['library_id'],library_revision=info['revision'],
                  counts={'questions':info['questions'],'ready':info['ready']},collections=info['collections'],files={})
    parent=output.parent; parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=output.name+'.staging-',dir=parent) as folder:
        staging=Path(folder)
        with closing(sqlite3.connect((source/'library.db').as_uri()+'?mode=ro',uri=True)) as source_conn, closing(sqlite3.connect(staging/'library.db')) as target_conn:
            source_conn.backup(target_conn)
        for rel in info['references']:
            dest=staging/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/rel,dest)
        manifest['files']['library.db']={'sha256':_sha(staging/'library.db'),'size':(staging/'library.db').stat().st_size}
        for rel in info['references']:
            path=staging/rel;manifest['files'][rel]={'sha256':_sha(path),'size':path.stat().st_size}
        (staging/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        from app.desktop.prepare import manifest as validate_manifest, verify_files, validate_database
        checked=validate_manifest(staging)
        verify_files(staging,checked,type('Progress',(),{'phase':'verify_seed','progress':lambda *a,**k:None})())
        validate_database(staging,checked)
        if output.exists(): shutil.rmtree(output)
        staging.rename(output)
    report['output_published']=True;report['manifest']=manifest
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--library',required=True,type=Path); parser.add_argument('--output',required=True,type=Path); parser.add_argument('--release-id',required=True); parser.add_argument('--report',type=Path); parser.add_argument('--force',action='store_true')
    args=parser.parse_args(); print(json.dumps(build(args.library,args.output,args.release_id,report_path=args.report,force=args.force),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
