"""Read canonical evidence or queue scoped, versioned reorganization."""
import uuid
from app.knowledge.index import snapshot,revision,catalog
from app.knowledge import mapping_versions as versions
from app.learning.workflows import enqueue


class KnowledgeService:
    def __init__(self,config,database):
        self.config,self.database=config,database

    def read(self):
        with self.database.session() as conn:
            return snapshot(conn)

    def organize(self,paper_id=None,body=None):
        body={} if body is None else dict(body)
        request_id=body.pop('request_id',None)
        scope=versions.normalize_request(body)
        if (scope['source_ids'] is not None or scope['refresh'] or request_id is not None) and not paper_id:
            raise ValueError('定向知识整理须指定试卷')
        if scope['refresh'] and request_id is None:raise ValueError('显式刷新须提供request_id以便安全重试')
        if request_id is not None:
            try:request_id=str(uuid.UUID(request_id))
            except (TypeError,ValueError,AttributeError):raise ValueError('知识整理请求标识无效') from None
        with self.database.session(write=True) as conn:
            if paper_id:
                paper=conn.execute('SELECT archived_at FROM papers WHERE id=?',(paper_id,)).fetchone()
                if not paper or paper['archived_at']:raise ValueError('试卷不存在或已归档')
            selected=versions.select_sources(conn,paper_id,scope)
            if request_id and len(selected)>500:raise ValueError('显式请求每次最多500份证据，请缩小范围')
            jobs=[];nodes=catalog(conn)
            for pid in sorted({s['paper_id'] for s in selected}):
                items=[s for s in selected if s['paper_id']==pid]
                for offset in range(0,len(items),500):
                    batch=items[offset:offset+500]
                    signature=revision({'sources':[(s['source_id'],s['source_revision']) for s in batch],
                                        'catalog':versions.catalog_revision(nodes),'rule':versions.RULE_REVISION})
                    request=request_id or str(uuid.uuid5(uuid.NAMESPACE_URL,'mathlens:index:v2:'+pid+':'+signature))
                    job=enqueue(conn,self.config.root,self.config.data,'organize_knowledge',pid,request,
                                knowledge_request={'source_ids':[s['source_id'] for s in batch],'refresh':True},
                                contract_version=versions.CONTRACT_VERSION)
                    jobs.append({'id':job['id'],'paper_id':pid,'status':job['status']})
            return {'jobs':jobs,'pending_sources':len(selected)}
