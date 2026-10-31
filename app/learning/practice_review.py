"""Versioned correction of exercise explanations, separate from student work."""
from __future__ import annotations

import json
import re

from app.knowledge import catalog, index, mapping_versions
from app.learning.practice_knowledge import binding_for, require_reviewed_references
from app.storage import annotation_cache
from app.storage.practice_materials import load

VERSION = '2.1'
FIELDS = ('expected', 'solution_note')


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS practice_solution_revisions(
        result_id TEXT NOT NULL REFERENCES learning_results(id),
        probe_id TEXT NOT NULL REFERENCES diagnostic_probes(id),
        previous_revision TEXT NOT NULL,new_revision TEXT NOT NULL,
        status TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL,
        PRIMARY KEY(result_id,probe_id))''')


def normalize_request(value):
    if not isinstance(value, dict) or set(value) - {'probes', 'note'}:
        raise ValueError('练习解答复核范围不合法')
    probes = value.get('probes');note = value.get('note', '')
    if (not isinstance(probes, list) or not 1 <= len(probes) <= 8 or
            not isinstance(note, str) or len(note) > 4000):
        raise ValueError('每次复核1–8道练习，说明最多4000字')
    output=[]
    for item in probes:
        if not isinstance(item, dict) or set(item) != {'probe_id', 'payload_revision', 'allowed_fields'}:
            raise ValueError('练习复核须明确原记录、解答版本和可改字段')
        pid, revision, fields = (item[k] for k in ('probe_id', 'payload_revision', 'allowed_fields'))
        if (not isinstance(pid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9:._-]{0,199}', pid)
                or not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{64}', revision)
                or not isinstance(fields, list) or not fields or any(f not in FIELDS for f in fields)
                or len(set(fields)) != len(fields)):
            raise ValueError('练习复核只允许修改答案和解答说明，不能更换题目或布置范围')
        output.append({'probe_id': pid, 'payload_revision': revision, 'allowed_fields': sorted(fields)})
    if len({p['probe_id'] for p in output}) != len(output):raise ValueError('复核练习不能重复')
    return {'probes': sorted(output, key=lambda p:p['probe_id']), 'note': note.strip()}


def capture(conn, data, paper_id, request):
    from app.learning.tasks import digest
    request = normalize_request(request)
    nodes = index.catalog(conn);known={n['id']:n for n in nodes}
    release = mapping_versions.catalog_revision(nodes)
    entries=[];topics=set()
    for item in request['probes']:
        row=conn.execute('SELECT * FROM diagnostic_probes WHERE id=? AND paper_id=?', (item['probe_id'],paper_id)).fetchone()
        if not row or conn.execute('SELECT 1 FROM retired_probes WHERE probe_id=?',(item['probe_id'],)).fetchone():
            raise ValueError('练习不存在、已停用或属于其他试卷')
        payload=json.loads(row['payload_json'])
        if digest(payload)!=item['payload_revision']:raise ValueError('练习解答版本已变化，请核对最新记录')
        binding=binding_for(conn,row['id'])
        if not binding:raise ValueError('练习缺少固定材料版本，请先恢复或复核原题；不能换用当前题库')
        manifest=load(data,binding['snapshot_key'],binding['snapshot_sha256'],())
        if (manifest['bank_id']!=row['bank_id'] or manifest['content_revision']!=binding['content_revision']
                or manifest['material_revision']!=binding['material_revision']):
            raise ValueError('练习固定材料与原记录不一致')
        annotation=annotation_cache.record(conn,binding['annotation_id'])
        if annotation is None:raise ValueError('原通用标注缺失，请恢复原版本')
        require_reviewed_references(conn,annotation,manifest)
        analysis=json.loads(annotation['payload_json'])
        own_topics={catalog.resolve(conn,b['topic_id']) for b in analysis['bindings']}
        if None in own_topics or not own_topics.issubset(known):raise ValueError('原题考点缺少可核对的规范定义')
        topics.update(own_topics)
        available=[];unavailable=[]
        for role in manifest['resources']:
            try:load(data,binding['snapshot_key'],binding['snapshot_sha256'],(role,));available.append(role)
            except ValueError as error:unavailable.append({'role':role,'reason':str(error)})
        entries.append({'request':item,'probe':dict(row),'binding':binding,'materials':manifest,
                        'available_roles':sorted(available),'unavailable_references':unavailable,
                        'topic_ids':sorted(own_topics),'annotation_record_sha256':catalog.digest(dict(annotation)),
                        'attempts':[dict(r) for r in conn.execute('SELECT * FROM probe_attempts WHERE probe_id=? ORDER BY id',(row['id'],))]})
    dependencies=mapping_versions.dependencies(nodes,topics)
    return {'request':request,'entries':entries,'catalog_revision':release,
            'catalog_nodes':[n for n in nodes if n['id'] in dependencies],
            'dependencies':dependencies}


def validate_input(conn, inputs, current):
    from app.learning.tasks import digest
    before=inputs['practice_review'];after=current['practice_review']
    ignored={'catalog_revision','catalog_nodes','dependencies'}
    if digest({k:v for k,v in before.items() if k not in ignored})!=digest({k:v for k,v in after.items() if k not in ignored}):
        raise ValueError('练习、作答或固定材料已变化，拒绝覆盖新记录')
    actual=mapping_versions.dependencies(after['catalog_nodes'],before['dependencies'])
    if actual!=before['dependencies']:raise ValueError('复核所用定义或层级已变化，请重新核对')
    if {k:v for k,v in inputs.items() if k!='practice_review'}!={k:v for k,v in current.items() if k!='practice_review'}:
        raise ValueError('试卷材料已变化，拒绝覆盖原任务')


def validate_math_delimiters(value, field):
    """Reject unclosed explicit delimiters; do not guess missing mathematics."""
    stack=[]
    for match in re.finditer(r'\$\$|\$|\\[()[\]]', value):
        start=match.start();slashes=0
        while start>0 and value[start-1]=='\\':slashes+=1;start-=1
        if slashes%2:continue
        token=match.group()
        if token in ('$','$$'):
            if stack and stack[-1]==token:stack.pop()
            elif stack:raise ValueError('公式分隔符不匹配：'+field)
            else:stack.append(token)
        elif token in ('\\(','\\['):
            if stack:raise ValueError('公式分隔符不能嵌套：'+field)
            stack.append(token)
        else:
            if not stack or stack.pop()!= {'\\)':'\\(','\\]':'\\['}[token]:
                raise ValueError('公式分隔符不匹配：'+field)
    if stack:raise ValueError('公式分隔符未闭合：'+field)


def save(conn, task, result_id, inputs, result):
    from app.learning.tasks import digest, require_read
    from app.learning.loop import save_version, stamp
    scope=inputs['practice_review'];available={e['probe']['id']:e for e in scope['entries']}
    revisions=result['revisions']
    if len({r['probe_id'] for r in revisions})!=len(revisions) or {r['probe_id'] for r in revisions}!=set(available):
        raise ValueError('复核须覆盖指定练习，不得遗漏、重复或修改其他题')
    for revision in revisions:
        entry=available[revision['probe_id']];old=json.loads(entry['probe']['payload_json'])
        if revision['payload_revision']!=entry['request']['payload_revision']:raise ValueError('修订未引用冻结的解答版本')
        require_read(conn,task,'practice_review',revision['probe_id'],'assignment',digest(entry['probe']))
        for role in entry['available_roles']:
            require_read(conn,task,'practice_material',revision['probe_id'],role,entry['materials']['resources'][role]['sha256'])
        for tid in entry['topic_ids']:
            node=next(n for n in scope['catalog_nodes'] if n['id']==tid)
            require_read(conn,task,'practice_review_definition',tid,scope['catalog_revision'],digest(node))
        changed={field for field in FIELDS if revision[field]!=old.get(field,'')}
        if not changed.issubset(entry['request']['allowed_fields']):raise ValueError('不能修改未授权的练习字段')
        if revision['status']!='needs_material' and 'question' not in entry['available_roles']:
            raise ValueError('缺少原题材料时只能保留待补材料，不能宣称解答已核实')
        if revision['status']=='corrected' and not changed:
            raise ValueError('修正须有可读原题和实际改动；缺题材料不能宣称已修正')
        if revision['status']!='corrected' and changed:raise ValueError('未核实或无需修改时须保留原解答')
        if revision['status']=='needs_material':
            if not revision['limitations']:raise ValueError('材料不足须指出具体缺口')
        elif not revision['checks'] or not revision['reason'].strip():raise ValueError('复核须保存实际验算与理由')
        for field in changed:validate_math_delimiters(revision[field],field)
        updated={**old,**{field:revision[field] for field in changed}}
        if changed:
            save_version(conn,'probe',revision['probe_id'],entry['probe'],'Agent限定字段修订练习解答：'+revision['reason'])
            conn.execute('UPDATE diagnostic_probes SET payload_json=? WHERE id=?',
                         (json.dumps(updated,ensure_ascii=False,sort_keys=True),revision['probe_id']))
        conn.execute('INSERT INTO practice_solution_revisions VALUES(?,?,?,?,?,?,?)',
                     (result_id,revision['probe_id'],digest(old),digest(updated),revision['status'],
                      json.dumps(revision,ensure_ascii=False,sort_keys=True),stamp()))
    return {'revised_probe_ids':[r['probe_id'] for r in revisions if r['status']=='corrected'],
            'needs_material_probe_ids':[r['probe_id'] for r in revisions if r['status']=='needs_material']}
