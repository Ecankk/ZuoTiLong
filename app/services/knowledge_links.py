"""Read-only, symmetric question/concept navigation; never selects exercises.

Both directions use the same validated projection. The bank projection is
cached by database content and material stat versions, not by an expiry timer.
No reasoning, answers, paths, or personal ability judgments leave this service.
"""
from copy import deepcopy
import json
from threading import RLock

from app.bank import annotations
from app.bank.access import aliases, access, preferences
from app.knowledge import catalog, index
from app.storage.knowledge_reads import navigation_snapshot


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

    def _build_bank_item(self,conn,row,nodes,view):
        names={n['id']:n['name'] for n in nodes}
        group=sorted(view.aliases(row['id']));bid=row['id']
        try:annotation=annotations.current(conn,self.config.data,bid,read_view=view)
        except (ValueError,OSError):annotation=None
        state='unannotated'
        if annotation:state=annotation['analysis']['status']
        elif conn.execute('SELECT 1 FROM question_annotation_links WHERE bank_id=?',(bid,)).fetchone():state='outdated'
        elif conn.execute('SELECT 1 FROM imported_question_annotations WHERE bank_id=?',(bid,)).fetchone():state='outdated'
        if state=='unannotated':
            packed=conn.execute('SELECT metadata_json FROM bank_resources WHERE bank_id=?',(bid,)).fetchone()
            imported_status=json.loads(packed[0]).get('annotation_status') if packed else None
            if imported_status in ('needs_review','needs_catalog'):state=imported_status
        meta=conn.execute('SELECT * FROM bank_identity WHERE bank_id=?',(bid,)).fetchone()
        meta=dict(meta) if meta else {}
        from app.bank.applicability import math_types
        deps={}
        if annotation:
            for table in ('question_annotations','imported_question_annotations'):
                record=conn.execute('SELECT dependencies_json FROM '+table+' WHERE id=?',(annotation['id'],)).fetchone()
                if record:deps=json.loads(record[0]);break
        return ({'_annotation':annotation,'bank_id':bid,'math_types':math_types(row['math_types_json'],meta.get('math_type')),'collection_id':row['collection_id'],'entity_id':min(group),'source':row['source'],
            'math_type':meta.get('math_type',0),'year':meta.get('year',''),'number':meta.get('number',0),'status':state,
            'topics':public_topics(annotation['analysis']['bindings'] if annotation else [],names,view.resolve),
            'annotation_id':annotation['id'] if annotation else None,
            'annotation_origin':'shared' if annotation and annotation.get('cache_provenance') else 'local' if annotation else None,
            'content_revision':annotation['content_revision'] if annotation else None,
            'material_revision':annotation['material_revision'] if annotation else None},deps)

    def _bank_index(self,conn,nodes):
        from app.storage.navigation_index import NavigationIndex
        with self._lock:
            return NavigationIndex(self.config).bank(conn,nodes,self._build_bank_item)

    def prepare_index(self):
        """Complete the one-time/incremental index upgrade before serving UI.

        Restarted services reuse persisted validation, never start a competing
        background whole-library warmup. No learner/source rows are written.
        """
        with navigation_snapshot(self.database) as conn:
            return len(self._bank_index(conn,index.catalog(conn)))

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
            p.title,p.exam_date,p.exam_date_precision,p.exam_date_unknown_reason,p.created_at,p.source_sha256,r.source_sha256 AS report_sha,r.report_json
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
                         'bank_id':bid,'collection_id':source['collection_id'] if source else None,'source_kind':'paper','paper_id':row['paper_id'],'paper_title':row['title'],
                         'question_id':row['id'],'number':row['number'],'date':row['exam_date'],
                         'exam_date_precision':row['exam_date_precision'],'exam_date_unknown_reason':row['exam_date_unknown_reason'],
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
                         'bank_id':row['bank_id'],'collection_id':source['collection_id'] if source else None,'source_kind':'probe','paper_id':row['paper_id'],
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
              offset=0,limit=15,paper_id=None,expected_revision=None,collection=None):
        if view not in ('completed','bank') or scope not in ('self','subtree'):raise ValueError('题目视图或范围无效')
        if role and role not in annotations.ROLES:raise ValueError('原子关联角色无效')
        if status and status not in ('ready','needs_review','needs_catalog','outdated','unannotated'):raise ValueError('标注状态无效')
        if math_type is not None and (type(math_type) is not int or math_type not in (1,2,3)):raise ValueError('数学类别无效')
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=50:raise ValueError('关联查询分页无效')
        with navigation_snapshot(self.database) as conn:
            from app.bank.collections import require
            if collection is not None:require(conn,collection)
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
                if collection is not None and item.get('collection_id')!=collection:continue
                if view=='bank' and ((math_type and math_type not in item['math_types']) or (year and year not in item['year']) or (status and item['status']!=status)):continue
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
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(self.config.library_database.resolve().as_uri()+'?mode=ro',uri=True)) as conn:
            conn.row_factory=sqlite3.Row
            with catalog.atomic(conn):return self._topics(conn,bank_ids)

    def _topics(self,conn,bank_ids):
        nodes = index.catalog(conn)
        from app.storage.navigation_index import NavigationIndex
        with self._lock:
            items = {i['bank_id']:i for i in NavigationIndex(self.config).bank(conn,nodes,self._build_bank_item,bank_ids)}
        if any(bid not in items for bid in bank_ids):raise ValueError('题库题目不存在')
        return {'catalog_revision':catalog.active_id(conn),'items':[deepcopy(items[bid]) for bid in bank_ids]}

    def bank_ids_for_topic(self,topic_id):
        """One validated bank pass for the paged library, without learner history."""
        with navigation_snapshot(self.database) as conn:
            nodes=index.catalog(conn)
            canonical=catalog.resolve(conn,topic_id) or topic_id
            selected=self._selected(nodes,canonical,'subtree')
            return {item['bank_id'] for item in self._bank_index(conn,nodes)
                    if any(t['topic_id'] in selected for t in item['topics'])}

    def resource_snapshot(self, bank=None):
        """Validated shared read projection for version-cached routed resources."""
        with navigation_snapshot(self.database) as conn:
            nodes=index.catalog(conn)
            if bank is None:bank=self._bank_index(conn,nodes)
            completed=self._completed(conn,nodes,bank,None)
            counts={n['id']:{'bank':set(),'completed':set()} for n in nodes}
            collection_counts={n['id']:{} for n in nodes}
            parents={n['id']:n['parent_id'] for n in nodes}
            for kind,items in (('bank',bank),('completed',completed)):
                for item in items:
                    for binding in item['topics']:
                        tid=binding['topic_id'];seen=set()
                        while tid in counts and tid not in seen:
                            seen.add(tid);counts[tid][kind].add(item['entity_id']);tid=parents[tid]
                        for target in seen:
                            cid=item.get('collection_id')
                            if cid:
                                grouped=collection_counts[target].setdefault(cid,{'bank':set(),'ready':set(),'completed':set()})
                                grouped[kind].add(item['entity_id'])
                                if kind=='bank' and item['status']=='ready':grouped['ready'].add(item['entity_id'])
            return dict(nodes=nodes,bank=bank,
                        redirects=(catalog.document(conn) or {}).get('document',{}).get('redirects',[]),
                        counts={tid:{k:len(v) for k,v in c.items()} for tid,c in counts.items()},
                        collection_counts={tid:[dict(collection_id=cid,**{k:len(v) for k,v in c.items()}) for cid,c in sorted(groups.items())] for tid,groups in collection_counts.items()})
