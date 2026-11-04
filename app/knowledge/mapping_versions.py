"""Version and dependency checks for evidence mappings, never new judgments."""
import json
from app.knowledge.catalog import digest

CONTRACT_VERSION = '1.8'
RULE_REVISION = 'evidence-mapping/2'


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS knowledge_mapping_versions(
        result_id TEXT NOT NULL,source_id TEXT NOT NULL,metadata_json TEXT NOT NULL,
        PRIMARY KEY(result_id,source_id),FOREIGN KEY(result_id,source_id)
        REFERENCES knowledge_mappings(result_id,source_id))''')


def normalize_request(value=None):
    value = {} if value is None else value
    if not isinstance(value,dict) or not set(value).issubset({'source_ids','refresh'}):
        raise ValueError('知识整理范围只接受source_ids和refresh')
    ids=value.get('source_ids')
    if ids is not None and (not isinstance(ids,list) or not 1<=len(ids)<=500
            or any(not isinstance(i,str) or not i.strip() for i in ids) or len(set(ids))!=len(ids)):
        raise ValueError('知识整理范围须为1–500个不同来源ID')
    refresh=value.get('refresh',False)
    if type(refresh) is not bool:raise ValueError('refresh须为布尔值')
    return {'source_ids':sorted(ids) if ids is not None else None,'refresh':refresh}


def semantic(node):
    origin=node.get('origin',{})
    # Legacy outline nodes have no mathematical definition. Their canonical
    # title is the only recorded scope and must not silently change meaning.
    return {'parent_id':node['parent_id'],'kind':origin.get('node_kind'),
            'definition':origin.get('definition',node['name']),
            'conditions':origin.get('conditions',[]),'boundaries':origin.get('boundaries',[]),
            'math_types':origin.get('math_types',[])}


def catalog_signature(nodes):
    return digest({n['id']:semantic(n) for n in nodes})


def catalog_revision(nodes):
    releases={n.get('origin',{}).get('catalog_revision') for n in nodes}
    return next(iter(releases)) if len(releases)==1 and None not in releases else 'outline:'+catalog_signature(nodes)


def dependencies(nodes,topic_ids):
    lookup={n['id']:n for n in nodes};output={}
    for topic in topic_ids:
        visited=set()
        while topic:
            if topic not in lookup or topic in visited:raise ValueError('知识映射引用未知节点或无效层级')
            visited.add(topic);node=lookup[topic]
            output[topic]=digest(semantic(node));topic=node['parent_id']
    return output


def metadata(inputs,mapping):
    nodes=inputs['knowledge_catalog']
    source=next((s for s in inputs['knowledge_sources'] if s['source_id']==mapping['source_id']),None)
    from app.learning.semantic_dependencies import signature
    return {'source_revision':mapping['source_revision'],
            'question_semantics':signature(source['content']['diagnosis']) if source and source['kind']=='question' else None,
            'catalog_revision':inputs['knowledge_catalog_revision'],
            'rule_revision':inputs['knowledge_rule_revision'],
            'dependencies':dependencies(nodes,mapping['topic_ids']),
            # With no mapped concepts, a semantic expansion may fill the gap.
            # Only unknown mappings need reconsideration; aliases do not count.
            'unmatched_catalog_signature':catalog_signature(nodes) if not mapping['topic_ids'] else None}


def inspect(conn,mapping,version,nodes):
    if version is None:return 'legacy_unversioned'
    if version.get('source_revision')!=mapping['source_revision']:return 'source_changed'
    if version.get('rule_revision')!=RULE_REVISION:return 'rule_changed'
    from app.knowledge.catalog import active_id,resolve
    release=active_id(conn)
    canonical=lambda nid:resolve(conn,nid,release) if release else nid
    try:
        saved=version['dependencies']
        current=dependencies(nodes,[canonical(nid) for nid in saved])
        resolved={nid:canonical(nid) for nid in saved}
        if set(current)!=set(resolved.values()) or any(current.get(resolved[nid])!=value for nid,value in saved.items()):
            return 'definition_changed'
        gap=version.get('unmatched_catalog_signature')
        if gap is not None and gap!=catalog_signature(nodes):return 'catalog_gap_changed'
    except (ValueError,KeyError,TypeError):return 'definition_changed'
    return 'current'


def latest(conn,nodes):
    has_versions=conn.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_mapping_versions'").fetchone()
    values={}
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_mappings'").fetchone():return values
    for row in conn.execute('SELECT * FROM knowledge_mappings ORDER BY created_at,rowid'):
        payload=json.loads(row['payload_json']);version=None
        if has_versions:
            record=conn.execute('SELECT metadata_json FROM knowledge_mapping_versions WHERE result_id=? AND source_id=?',
                                (row['result_id'],row['source_id'])).fetchone()
            if record:version=json.loads(record[0])
        values[(row['source_id'],row['source_revision'])]={'mapping':payload,'version':version,
            'status':inspect(conn,payload,version,nodes),'result_id':row['result_id']}
    from app.learning.semantic_dependencies import adopt_mappings
    adopt_mappings(conn,values)
    return values


def select_sources(conn,paper_id,request=None):
    from app.knowledge.index import sources,catalog
    scope=normalize_request(request);all_sources=sources(conn,paper_id)
    if scope['source_ids'] is not None:
        available={s['source_id'] for s in all_sources}
        if not set(scope['source_ids']).issubset(available):raise ValueError('知识证据不属于当前试卷或已归档')
        all_sources=[s for s in all_sources if s['source_id'] in scope['source_ids']]
    if scope['refresh']:return all_sources
    saved=latest(conn,catalog(conn))
    return [s for s in all_sources if saved.get((s['source_id'],s['source_revision']),{}).get('status')!='current']


def validate_current(conn,inputs,result):
    """Ignore unrelated directory edits, require selected math to stay equal."""
    from app.knowledge.index import catalog
    if inputs['knowledge_rule_revision']!=RULE_REVISION:
        raise ValueError('整理规则已变化，请按当前规则重新整理本批证据')
    nodes=catalog(conn)
    for mapping in result['mappings']:
        if inspect(conn,mapping,metadata(inputs,mapping),nodes)!='current':
            raise ValueError('所引用考点定义或整理规则已变化，请按当前目录重整本批证据')


def read_context(inputs,payload):
    if not isinstance(payload,dict) or not set(payload).issubset({'source_ids','topic_ids','knowledge_query'}) or len(payload)>1:
        raise ValueError('知识整理每次只读取来源、定义或查询其中一种')
    if not payload:return None,[]
    if 'source_ids' in payload:
        ids=payload['source_ids']
        if not isinstance(ids,list) or not 1<=len(ids)<=8 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
            raise ValueError('每次读取1–8个不同来源ID')
        return None,[]
    nodes=inputs['knowledge_catalog'];lookup={n['id']:n for n in nodes}
    if 'topic_ids' in payload:
        ids=payload['topic_ids']
        if not isinstance(ids,list) or not 1<=len(ids)<=30 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
            raise ValueError('每次读取1–30个不同规范考点定义')
        if not set(ids).issubset(lookup):raise ValueError('考点不属于本任务捕获目录')
        return {'catalog_revision':inputs['knowledge_catalog_revision'],'nodes':[lookup[i] for i in ids]},ids
    query=payload['knowledge_query']
    if not isinstance(query,dict) or not set(query).issubset({'query','parent_id','kinds','offset','limit'}):
        raise ValueError('目录查询字段不合法')
    text=query.get('query','');parent=query.get('parent_id');kinds=query.get('kinds')
    offset=query.get('offset',0);limit=query.get('limit',40)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:raise ValueError('目录查询分页不合法')
    if not isinstance(text,str) or parent is not None and (not isinstance(parent,str) or parent not in lookup):raise ValueError('目录查询范围不合法')
    if kinds is not None and (not isinstance(kinds,list) or any(k not in ('subject','chapter','topic','atom') for k in kinds)):
        raise ValueError('目录查询节点类型不合法')
    from app.knowledge.catalog import normalized
    key=normalized(text)
    def matches(node):
        tid=node['id'];inside=parent is None
        while tid and not inside:
            inside=tid==parent;tid=lookup[tid]['parent_id']
        kind=node.get('origin',{}).get('node_kind')
        return inside and (not kinds or kind in kinds) and (not key or any(key in normalized(t) for t in (node['name'],node['id'],*node['aliases'])))
    found=sorted((n for n in nodes if matches(n)),key=lambda n:n['id'])
    return {'catalog_revision':inputs['knowledge_catalog_revision'],'total':len(found),'offset':offset,'limit':limit,
            'items':[{k:n[k] for k in ('id','parent_id','name','aliases')} for n in found[offset:offset+limit]],
            'reading':'摘要仅作定位；用topic_ids读取捕获定义后再引用。'},[]
