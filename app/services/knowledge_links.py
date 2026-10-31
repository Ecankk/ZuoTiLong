"""Read-only, symmetric question/concept navigation; never selects exercises.

Both directions use the same validated projection. The bank projection is
cached by database content and material stat versions, not by an expiry timer.
No reasoning, answers, paths, or personal ability judgments leave this service.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from threading import RLock

from app.bank import annotations
from app.bank.access import aliases, access, preferences
from app.knowledge import catalog, index
from app.storage.knowledge_reads import navigation_snapshot
from app.storage.boundaries import library_root, material_path, schema_rows


def _json(text, default=None):
    try:return json.loads(text) if text else default
    except (ValueError, TypeError):return default


def public_topics(bindings,names,canonical):
    """Merged historical IDs display once; preserve strongest recorded role."""
    found={};priority={'primary':0,'supporting':1,'prerequisite':2}
    for binding in bindings:
        tid=canonical(binding['topic_id'])
        if tid not in names:continue
        old=found.get(tid)
        role=binding['role']
        if old and priority[old['role']]<priority[role]:role=old['role']
        found[tid]={'topic_id':tid,'name':names[tid],'role':role,
                    'stages':sorted(set(binding['stages'])|set(old['stages'] if old else []))}
    return list(found.values())


class KnowledgeLinksService:
    def __init__(self, config, database):
        self.config, self.database = config, database
        self._lock = RLock()
        self._bank_key = None
        self._bank = None

    def _signature(self, conn):
        """Include actual mutable content and every referenced image digest.

        Exposure/draft writes do not invalidate mathematical navigation. A file
        replacement, missing file, identity withdrawal, cache switch, definition
        edit or new annotation does. File bytes are verified by current() when
        building. Hash bytes here too: Windows ctime is creation time and cannot
        detect equal-size edits with a restored mtime.
        """
        tables = ('bank_questions','bank_resources','bank_identity','bank_links','bank_identity_reviews',
                  'question_annotations','question_annotation_links','prepared_annotation_ids',
                  'imported_question_annotations','annotation_cache_state','annotation_cache_packages',
                  'knowledge_catalog_state')
        present = {r['name'] for r in schema_rows(conn)}
        digest = hashlib.sha256()
        for table in tables:
            if table not in present:continue
            digest.update(table.encode())
            for row in conn.execute('SELECT * FROM '+table+' ORDER BY rowid'):
                for cell in row:
                    value=str(cell).encode();digest.update(str(len(value)).encode()+b':'+value)
        release=catalog.document(conn)
        digest.update(catalog.encode(release).encode())
        base=os.path.abspath(library_root(self.config.data)/'bank-assets')
        safe_base=(library_root(self.config.data)/'bank-assets').resolve()
        seen_files=set()
        for row in conn.execute('SELECT question_path,answer_path,analysis_path FROM bank_resources ORDER BY bank_id'):
            for value in row:
                if not value:continue
                path = os.path.abspath(material_path(self.config.data, value))
                if path in seen_files:continue
                seen_files.add(path)
                if os.path.commonpath((base,path))!=base:
                    digest.update(b'outside');continue
                try:
                    resolved=Path(path).resolve()
                    if not resolved.is_relative_to(safe_base):
                        digest.update(b'outside');continue
                    with open(resolved,'rb') as material:
                        token=(path,hashlib.file_digest(material,'sha256').hexdigest())
                except OSError:token = (str(path),'missing')
                digest.update(repr(token).encode())
        return digest.hexdigest()

    def _bank_index(self, conn, nodes):
        key = self._signature(conn)
        with self._lock:
            if key == self._bank_key:return self._bank
            from app.bank.annotation_view import AnnotationReadView
            read_view=AnnotationReadView(conn,self.config.data)
            names = {n['id']:n['name'] for n in nodes}
            redirect = {r['old_id']:r['target_id'] for r in (catalog.document(conn) or {}).get('document',{}).get('redirects',[])}
            canonical = lambda tid: tid if tid in names else redirect.get(tid)
            identities = {r['bank_id']:dict(r) for r in conn.execute('SELECT * FROM bank_identity')}
            groups = {};items = []
            for row in conn.execute("SELECT id,source FROM bank_questions WHERE source!='本地示例题库' ORDER BY id"):
                bid = row['id']
                if bid not in groups:
                    group = sorted(read_view.aliases(bid))
                    for member in group:groups[member] = group
                group = groups[bid]
                try:annotation = annotations.current(conn,self.config.data,bid,read_view=read_view)
                except (ValueError, OSError):annotation = None
                state = 'unannotated'
                if annotation:state = annotation['analysis']['status']
                elif conn.execute('SELECT 1 FROM question_annotation_links WHERE bank_id=?',(bid,)).fetchone():state = 'outdated'
                elif conn.execute("SELECT 1 FROM imported_question_annotations WHERE bank_id=?",(bid,)).fetchone():state = 'outdated'
                bindings=public_topics(annotation['analysis']['bindings'] if annotation else [],names,canonical)
                meta = identities.get(bid,{})
                items.append({'bank_id':bid,'entity_id':min(group),'source':row['source'],
                              'math_type':meta.get('math_type',0),'year':meta.get('year',''),
                              'number':meta.get('number',0),'status':state,'topics':bindings,
                              'annotation_id':annotation['id'] if annotation else None,
                              'annotation_origin':'shared' if annotation and annotation.get('cache_provenance') else 'local' if annotation else None,
                              'content_revision':annotation['content_revision'] if annotation else None,
                              'material_revision':annotation['material_revision'] if annotation else None})
            # If files changed while validation ran, this read is not published.
            if key != self._signature(conn):raise ValueError('题库材料正在变化，请稍后重新读取关联')
            self._bank_key, self._bank = key, items
            return items

    def _completed(self, conn, nodes, bank, paper_id):
        snapshot = index.snapshot(conn)
        by_source = {}
        for node in snapshot['nodes']:
            for scope in node['scopes']:
                if scope['mapping_status']=='current':by_source.setdefault(scope['source_id'],set()).add(node['skill_id'])
        names = {n['id']:n['name'] for n in nodes}
        bank_by_id = {b['bank_id']:b for b in bank}
        rows = []
        for row in conn.execute('''SELECT q.id,q.paper_id,q.number,d.report_id,d.diagnosis_json,
            p.title,p.exam_date,p.created_at,p.source_sha256,r.source_sha256 AS report_sha,r.report_json
            FROM questions q JOIN question_diagnoses d ON d.question_id=q.id
            JOIN papers p ON p.id=q.paper_id JOIN agent_reports r ON r.id=d.report_id
            WHERE p.archived_at IS NULL ORDER BY q.id'''):
            if paper_id and row['paper_id']!=paper_id:continue
            q = _json(row['diagnosis_json'],{});report = _json(row['report_json'],{})
            evidence = q.get('answer_evidence') or {}
            if (evidence.get('student_state')!='visible' or not evidence.get('student_work','').strip()
                    or q.get('correctness') not in ('correct','wrong','partial')
                    or report.get('review',{}).get('status')!='verified'
                    or row['source_sha256'] and row['source_sha256']!=row['report_sha']):continue
            binding = conn.execute('SELECT bank_id FROM paper_question_bindings WHERE question_id=? AND report_id=?',
                                   (row['id'],row['report_id'])).fetchone()
            bid = binding[0] if binding else None
            source = bank_by_id.get(bid)
            rows.append({'id':row['id'],'entity_id':source['entity_id'] if source else 'original:'+row['id'],
                         'bank_id':bid,'source_kind':'paper','paper_id':row['paper_id'],'paper_title':row['title'],
                         'question_id':row['id'],'number':row['number'],'date':row['exam_date'] or row['created_at'],
                         'state':q['correctness'],'report_id':row['report_id'],
                         'topic_ids':sorted(by_source.get(row['id'],set())),'protected':False})
        for row in conn.execute('''SELECT a.*,d.paper_id,d.question_id,d.bank_id,p.title,p.exam_date
            FROM probe_attempts a JOIN diagnostic_probes d ON d.id=a.probe_id
            JOIN papers p ON p.id=d.paper_id WHERE p.archived_at IS NULL ORDER BY a.created_at,a.rowid'''):
            if paper_id and row['paper_id']!=paper_id:continue
            assessment = _json(row['assessment_json'],{})
            if type(assessment.get('correct')) is not bool or assessment.get('method')=='explicit_answer_match':continue
            tids = set(by_source.get(row['probe_id'],set()))
            # Attempt evidence uses versioned event IDs; only the saved current
            # mapping can contribute concepts, never the free-text skill label.
            prefix = row['id']+':'
            for sid, related in by_source.items():
                if sid.startswith(prefix):tids.update(related)
            source = bank_by_id.get(row['bank_id'])
            rows.append({'id':row['id'],'entity_id':source['entity_id'] if source else 'bank:'+row['bank_id'],
                         'bank_id':row['bank_id'],'source_kind':'probe','paper_id':row['paper_id'],
                         'paper_title':row['title'],'question_id':row['question_id'],'probe_id':row['probe_id'],
                         'attempt_id':row['id'],'number':source['number'] if source else None,
                         'date':row['created_at'],'state':'correct' if assessment['correct'] else 'wrong',
                         'assisted':bool(row['answer_exposed']),'topic_ids':sorted(tids),
                         'protected':not access(conn,row['bank_id'])['can_view']})
        for row in rows:
            row['topics'] = [{'topic_id':tid,'name':names[tid],'role':'coverage','stages':[]}
                             for tid in row.pop('topic_ids') if tid in names]
        return rows

    def _read(self, conn, paper_id=None):
        nodes = index.catalog(conn)
        bank = self._bank_index(conn,nodes)
        completed = self._completed(conn,nodes,bank,paper_id)
        return nodes,bank,completed

    def _revision(self,conn,bank,completed):
        # Use this request's immutable result, not the shared cache key: another
        # reader can populate a newer database snapshot while this one finishes.
        return catalog.digest({'catalog':catalog.active_id(conn),'bank':bank,'completed':completed,
                               'reserved':preferences(conn)['reserved']})

    @staticmethod
    def _selected(nodes, topic_id, scope):
        lookup = {n['id']:n for n in nodes}
        if not topic_id:return None
        if topic_id not in lookup:raise ValueError('当前目录没有这个考点')
        selected = {topic_id}
        if scope=='subtree':
            children = {}
            for node in nodes:children.setdefault(node['parent_id'],[]).append(node['id'])
            queue = [topic_id]
            while queue:
                for child in children.get(queue.pop(),[]):
                    if child not in selected:selected.add(child);queue.append(child)
        return selected

    def summary(self,paper_id=None):
        with navigation_snapshot(self.database) as conn:
            nodes,bank,completed = self._read(conn,paper_id)
            counts = {n['id']:{'bank':set(),'ready':set(),'completed':set(),'source_records':set()} for n in nodes}
            parents = {n['id']:n['parent_id'] for n in nodes}
            for kind,items in (('bank',bank),('completed',completed)):
                for item in items:
                    targets = set()
                    for binding in item['topics']:
                        tid = binding['topic_id']
                        while tid and tid not in targets and tid in counts:
                            targets.add(tid);tid = parents[tid]
                    for tid in targets:
                        counts[tid][kind].add(item['entity_id'])
                        if kind=='bank':
                            counts[tid]['source_records'].add(item['bank_id'])
                            if item['status']=='ready':counts[tid]['ready'].add(item['entity_id'])
            return {'catalog_revision':catalog.active_id(conn),'navigation_revision':self._revision(conn,bank,completed),
                    'nodes':{tid:{k:len(v) for k,v in value.items()} for tid,value in counts.items()},
                    'total_completed':len({i['entity_id'] for i in completed}),'total_bank':len({i['entity_id'] for i in bank}),
                    'source_records':len(bank),'default_view':'completed' if completed else 'bank'}

    def links(self,*,view='bank',topic_id=None,scope='subtree',role=None,status=None,math_type=None,year=None,
              offset=0,limit=15,paper_id=None,expected_revision=None):
        if view not in ('completed','bank') or scope not in ('self','subtree'):raise ValueError('题目视图或范围无效')
        if role and role not in annotations.ROLES:raise ValueError('原子关联角色无效')
        if status and status not in ('ready','needs_review','needs_catalog','outdated','unannotated'):raise ValueError('标注状态无效')
        if math_type is not None and (type(math_type) is not int or math_type not in (1,2,3)):raise ValueError('数学类别无效')
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=50:raise ValueError('关联查询分页无效')
        with navigation_snapshot(self.database) as conn:
            nodes,bank,completed = self._read(conn,paper_id)
            revision = catalog.active_id(conn)
            if expected_revision and expected_revision!=revision:raise ValueError('目录版本已更新，请刷新考点树')
            canonical = catalog.resolve(conn,topic_id) if topic_id else None
            if topic_id and not canonical and any(n['id']==topic_id for n in nodes):canonical=topic_id
            if topic_id and not canonical:raise ValueError('当前目录没有这个考点')
            selected = self._selected(nodes,canonical,scope)
            reserved = preferences(conn)['reserved']
            reserved_entities={i['entity_id'] for i in bank if {'math_type':i['math_type'],'year':i['year']} in reserved}
            groups = {}
            for item in bank if view=='bank' else completed:
                if view=='bank' and ((math_type and item['math_type']!=math_type) or (year and year not in item['year']) or (status and item['status']!=status)):continue
                matches = [t for t in item['topics'] if (selected is None or t['topic_id'] in selected) and (not role or t['role']==role)]
                if selected is not None and not matches or role and not matches:continue
                public = deepcopy(item)
                if view=='bank':public['reserved']=item['entity_id'] in reserved_entities
                if item.get('protected'):public['topics']=[];matches=[]
                public['matched_topics'] = matches
                group = groups.setdefault(item['entity_id'],{'entity_id':item['entity_id'],'sources':[]})
                group['sources'].append(public)
            ordered = sorted(groups.values(),key=lambda g:g['entity_id'])
            return {'catalog_revision':revision,'navigation_revision':self._revision(conn,bank,completed),
                    'topic_id':canonical,'view':view,'scope':scope,
                    'total':len(ordered),'source_records':sum(len(g['sources']) for g in ordered),
                    'offset':offset,'limit':limit,'next_offset':offset+limit if offset+limit<len(ordered) else None,
                    'items':ordered[offset:offset+limit]}

    def topics(self,bank_ids):
        if not 1<=len(bank_ids)<=50 or len(set(bank_ids))!=len(bank_ids):raise ValueError('每次读取1–50道不同题目的原子标签')
        with navigation_snapshot(self.database) as conn:
            nodes = index.catalog(conn)
            items = {i['bank_id']:i for i in self._bank_index(conn,nodes)}
            if any(bid not in items for bid in bank_ids):raise ValueError('题库题目不存在')
            return {'catalog_revision':catalog.active_id(conn),'items':[deepcopy(items[bid]) for bid in bank_ids]}
