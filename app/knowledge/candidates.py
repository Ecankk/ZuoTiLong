"""Import fixed source evidence without promoting it to canonical knowledge."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from app.knowledge.catalog import atomic, digest, encode

SOURCE = '11408Advance-mcp:mathematics'


def read_11408(directory):
    folder = Path(directory).resolve()
    manifest_path = folder / 'index.json'
    if not folder.is_dir() or not manifest_path.is_file():
        raise ValueError('找不到已导出的11408候选清单')
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    revision = manifest.get('source_commit', '')
    if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('候选资料必须绑定完整源码commit')
    chapters = manifest.get('chapters')
    if not isinstance(chapters, list) or not chapters:
        raise ValueError('候选清单缺少分章文件')
    entries, seen, chapter_keys = [], set(), set()
    for item in chapters:
        key = item['key']
        if key in chapter_keys:raise ValueError('候选章节重复')
        chapter_keys.add(key)
        path = (folder / item['path']).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError('候选章节路径越界或不存在')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('候选章节散列不匹配，不能沿用旧来源版本')
        value = json.loads(raw)
        if value.get('source_commit') != revision:
            raise ValueError('候选章节混用了不同源码版本')
        for plural, kind in (('atoms', 'atom'), ('combinations', 'combination')):
            records = value.get(plural, [])
            if len(records) != item[plural]:raise ValueError('候选章节记录数量不一致')
            for record in records:
                rid = record['id']
                if rid in seen:raise ValueError('候选ID重复，须核对来源')
                seen.add(rid)
                if record.get('source_commit') != revision or record.get('content_review') != 'source_unreviewed':
                    raise ValueError('导出来源版本/原始审核状态不符合候选契约')
                if hashlib.sha256(record['raw'].encode('utf-8')).hexdigest() != record['content_sha256']:
                    raise ValueError('候选原始内容散列不匹配')
                # The raw row is provenance only. Upstream personal status,
                # importance and breakpoint notes are never learning events.
                entries.append({'id': rid, 'kind': kind, 'chapter_key': key, 'record': record})
    atoms = {e['id'] for e in entries if e['kind'] == 'atom'}
    for entry in entries:
        if entry['kind'] == 'combination' and not set(entry['record']['atom_chain']).issubset(atoms):
            raise ValueError('组合链引用不存在的原子候选')
    for filename, kind in (('atoms.jsonl', 'atom'), ('combinations.jsonl', 'combination')):
        path = folder / filename
        if path.exists():
            rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
            exported = {r['id']: r for r in rows}
            chapter_rows = {e['id']: e['record'] for e in entries if e['kind'] == kind}
            if len(exported) != len(rows) or exported != chapter_rows:
                raise ValueError('候选总表与分章内容不一致')
    return {'source': SOURCE, 'revision': revision,
            'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'metadata': {'chapters': chapters, 'content_review': 'source_unreviewed',
                         'personal_status_imported': False}, 'entries': entries}


def read_supplement(directory):
    """Version a small, evidenced source pack without approving its claims."""
    from app.knowledge.catalog import ID
    folder=Path(directory).resolve();path=folder/'index.json'
    if not path.is_file() or path.stat().st_size>5*1024*1024:
        raise ValueError('补充来源清单不存在或过大')
    manifest=json.loads(path.read_bytes())
    fields={'schema_version','source','revision','title','references','entries'}
    if not isinstance(manifest,dict) or set(manifest)!=fields or manifest['schema_version']!='mathlens.knowledge-source/v1':
        raise ValueError('补充来源清单字段或格式不合法')
    if not isinstance(manifest['source'],str) or not ID.fullmatch(manifest['source']) or manifest['source']==SOURCE:
        raise ValueError('补充来源标识不合法或冒用11408来源')
    if manifest['revision']!=digest({k:v for k,v in manifest.items() if k!='revision'}):
        raise ValueError('补充来源版本与清单内容不匹配，请保留旧版并创建新版')
    if not isinstance(manifest['title'],str) or not manifest['title'].strip():raise ValueError('补充来源须有标题')
    references=manifest['references'];refs={}
    if not isinstance(references,list) or not 1<=len(references)<=50:raise ValueError('须提供1–50份实际来源依据')
    for ref in references:
        if not isinstance(ref,dict) or set(ref)!={'id','title','url','locator','retrieved_at','path','sha256'}:
            raise ValueError('补充来源依据字段不完整')
        if any(not isinstance(ref[k],str) or not ref[k].strip() for k in ref):raise ValueError('来源依据字段不能为空')
        if not ID.fullmatch(ref['id']) or ref['id'] in refs:raise ValueError('来源依据ID不合法或重复')
        parsed=urlsplit(ref['url'])
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('来源URL须为无凭据的HTTP地址')
        resource=(folder/ref['path']).resolve()
        if Path(ref['path']).is_absolute() or not resource.is_relative_to(folder) or not resource.is_file():
            raise ValueError('补充来源依据文件不存在或路径越界')
        if hashlib.sha256(resource.read_bytes()).hexdigest()!=ref['sha256']:
            raise ValueError('补充来源依据散列不匹配')
        refs[ref['id']]=ref
    entries=manifest['entries'];ids=set();normalized=[]
    if not isinstance(entries,list) or not 1<=len(entries)<=10000:raise ValueError('补充来源条目数量不合法')
    for row in entries:
        required={'id','chapter_key','statement','conditions','boundaries','reference_ids','source_locator'}
        if not isinstance(row,dict) or set(row)!=required:raise ValueError('补充候选字段不完整或混入个人状态')
        if any(not isinstance(row[k],str) or not row[k].strip() for k in ('id','chapter_key','statement','source_locator')):
            raise ValueError('补充候选的ID、章节、数学说明及定位不能为空')
        if not ID.fullmatch(row['id']) or not ID.fullmatch(row['chapter_key']) or row['id'] in ids:
            raise ValueError('补充候选ID/章节不合法或重复')
        for key in ('conditions','boundaries'):
            if not isinstance(row[key],list) or any(not isinstance(s,str) or not s.strip() for s in row[key]):
                raise ValueError('补充候选条件/边界须为文字数组')
        selected=row['reference_ids']
        if not isinstance(selected,list) or not selected or any(not isinstance(r,str) for r in selected) or len(set(selected))!=len(selected) or not set(selected).issubset(refs):
            raise ValueError('补充候选须引用已核文件依据，不得悬空或重复')
        ids.add(row['id']);raw=encode(row)
        record={**row,'raw':raw,'content_sha256':hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                'content_review':'source_unreviewed','source_path':refs[selected[0]]['path'],
                'source_line':None,'statement_kind':'project_paraphrase',
                'references':[refs[r] for r in selected]}
        normalized.append({'id':row['id'],'kind':'atom','chapter_key':row['chapter_key'],'record':record})
    return {'source':manifest['source'],'revision':manifest['revision'],'manifest_sha256':digest(manifest),
            'metadata':{'title':manifest['title'],'format':manifest['schema_version'],'references':references,
                        'content_review':'source_unreviewed','personal_status_imported':False,
                        'manifest_digest_format':'canonical-json'},'entries':normalized}


def import_source(conn,directory):
    path=Path(directory).resolve()/'index.json'
    if not path.is_file() or path.stat().st_size>5*1024*1024:raise ValueError('找不到合法候选来源清单')
    manifest=json.loads(path.read_bytes())
    if not isinstance(manifest,dict):raise ValueError('候选来源清单须为JSON对象')
    value=read_supplement(directory) if manifest.get('schema_version')=='mathlens.knowledge-source/v1' else read_11408(directory)
    return _import_value(conn,value)


def import_11408(conn, directory):
    return _import_value(conn,read_11408(directory))


def _import_value(conn,value):
    source_id = 'source-' + digest({'source': value['source'], 'revision': value['revision']})
    from app.storage.catalog_packages import check_raw_source
    check_raw_source(conn, value, source_id)
    old = conn.execute('SELECT * FROM knowledge_source_versions WHERE source=? AND revision=?',
                       (value['source'], value['revision'])).fetchone()
    if old:
        if old['manifest_sha256'] != value['manifest_sha256']:
            raise ValueError('相同来源版本出现不同内容，禁止覆盖')
        saved = {r['id']: (r['kind'], r['content_sha256'], r['payload_json']) for r in conn.execute(
            'SELECT * FROM knowledge_source_entries WHERE source_version_id=?', (old['id'],))}
        expected = {e['id']: (e['kind'], e['record']['content_sha256'], encode(e)) for e in value['entries']}
        if saved != expected:raise ValueError('既有候选数据与固定导出不一致，禁止静默修补')
        return {'source_version_id': old['id'], 'reused': True, 'entries': len(saved)}
    with atomic(conn):
        conn.execute('INSERT INTO knowledge_source_versions VALUES(?,?,?,?,?)',
                     (source_id, value['source'], value['revision'], value['manifest_sha256'], encode(value['metadata'])))
        for entry in value['entries']:
            conn.execute('INSERT INTO knowledge_source_entries VALUES(?,?,?,?,?)',
                         (source_id, entry['id'], entry['kind'], entry['record']['content_sha256'], encode(entry)))
    return {'source_version_id': source_id, 'reused': False, 'entries': len(value['entries']),
            'atoms': sum(e['kind'] == 'atom' for e in value['entries']),
            'combinations': sum(e['kind'] == 'combination' for e in value['entries'])}


def browse(conn, *, source_version_id, chapter=None, kind='atom', query='', offset=0, limit=40):
    if kind not in ('atom', 'combination') or not 1 <= limit <= 100 or offset < 0:
        raise ValueError('候选查询类型或分页不合法')
    if not conn.execute('SELECT 1 FROM knowledge_source_versions WHERE id=?', (source_version_id,)).fetchone():
        raise ValueError('候选来源版本不存在')
    from app.knowledge.catalog import document
    current=document(conn)
    resolutions={(r['source_version_id'],r['source_id']):r for r in current['document']['source_resolutions']} if current else {}
    matches = []
    for row in conn.execute('SELECT * FROM knowledge_source_entries WHERE source_version_id=? AND kind=? ORDER BY id', (source_version_id, kind)):
        entry = json.loads(row['payload_json']);record = entry['record']
        if chapter and entry['chapter_key'] != chapter:continue
        if query and query.casefold() not in (record['id'] + ' ' + record['statement']).casefold():continue
        resolution=resolutions.get((source_version_id,row['id']))
        matches.append({'id': row['id'], 'chapter_key': entry['chapter_key'], 'kind': kind,
                        'statement': record['statement'], 'source_path': record['source_path'],
                        'source_line': record['source_line'], 'source_locator': record.get('source_locator'),
                        'content_sha256': row['content_sha256'], 'source_import_status': 'source_unreviewed',
                        'catalog_disposition':resolution['disposition'] if resolution else 'pending',
                        'canonical_node_ids':resolution['node_ids'] if resolution else []})
    return {'source_version_id': source_version_id, 'total': len(matches),
            'items': matches[offset:offset + limit], 'offset': offset, 'limit': limit}
