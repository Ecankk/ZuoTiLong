"""Application boundary for the shared catalogue; learners only read it."""
from app.knowledge import catalog, candidates


class KnowledgeCatalogService:
    def __init__(self, config, database):
        self.config, self.database = config, database

    def search(self, **query):
        with self.database.session() as conn:
            return catalog.search(conn, **query)

    def summary(self):
        with self.database.session() as conn:
            current = catalog.document(conn)
            versions = [dict(row) for row in conn.execute('SELECT id,source,revision FROM knowledge_source_versions ORDER BY id')]
            for source in versions:
                source['counts'] = {row['kind']: row['n'] for row in conn.execute(
                    'SELECT kind,count(*) n FROM knowledge_source_entries WHERE source_version_id=? GROUP BY kind', (source['id'],))}
                atom_ids={r[0] for r in conn.execute("SELECT id FROM knowledge_source_entries WHERE source_version_id=? AND kind='atom'",(source['id'],))}
                resolutions=[r for r in current['document']['source_resolutions'] if r['source_version_id']==source['id'] and r['source_id'] in atom_ids] if current else []
                source['catalog_dispositions']={kind:sum(r['disposition']==kind for r in resolutions) for kind in catalog.DISPOSITIONS}
                source['unresolved_atoms']=source['counts'].get('atom',0)-sum(r['disposition']!='pending' for r in resolutions)
            return {'active_release_id': current['id'] if current else None,
                    'published_nodes': len(current['document']['nodes']) if current else 0,
                    'legacy_outline_nodes': conn.execute('SELECT count(*) FROM knowledge_nodes').fetchone()[0],
                    'candidate_sources': versions,
                    'policy': '普通学习任务只引用已发布目录；候选存在不代表已核或可用于题目标注。'}

    def candidates(self, **query):
        with self.database.session() as conn:
            return candidates.browse(conn, **query)

    def release(self, release_id):
        with self.database.session() as conn:
            return catalog.document(conn, release_id)

    def releases(self):
        with self.database.session() as conn:
            return {'releases': [dict(row) for row in conn.execute(
                'SELECT id,parent_id,state,content_sha256,reviewer,published_at FROM knowledge_catalog_releases ORDER BY rowid DESC')]}

    def import_candidates(self,directory):
        with self.database.session(write=True,library_write=True) as conn:
            # A sqlite connection context alone does not start a transaction.
            # Keep the nested importer savepoint inside an explicit outer one
            # until the source evidence and its metadata are both complete.
            with catalog.atomic(conn):
                result=candidates.import_source(conn,directory)
                import json
                row=conn.execute('SELECT metadata_json FROM knowledge_source_versions WHERE id=?',
                                 (result['source_version_id'],)).fetchone()
                metadata=json.loads(row['metadata_json'])
                if metadata.get('format')=='mathlens.knowledge-source/v1':
                    from app.storage.knowledge_sources import preserve_supplement
                    evidence_root=preserve_supplement(self.config.data,directory,result['source_version_id'])
                    metadata['evidence_root']=evidence_root
                    conn.execute('UPDATE knowledge_source_versions SET metadata_json=? WHERE id=?',
                                 (catalog.encode(metadata),result['source_version_id']))
                    result['evidence_root']=evidence_root
                return result

    def prepare(self,body):
        from app.knowledge.preparation import start
        with self.database.session(write=True) as conn:
            return start(conn,self.config.root,self.config.data,**body)

    def preparation(self):
        from app.knowledge.preparation import snapshot
        with self.database.session() as conn:return snapshot(conn)

    def preparation_action(self,run_id,operation):
        from app.knowledge.preparation import action
        with self.database.session(write=True) as conn:
            return action(conn,self.config.root,self.config.data,run_id,operation)

    def export_package(self):
        from app.knowledge.packages import export_package
        with self.database.session() as conn:
            conn.execute('BEGIN')
            return export_package(conn)

    def preview_package(self, package):
        from app.knowledge.packages import validate_package
        preview = validate_package(package)
        with self.database.session() as conn:
            return {**preview, 'current_release_id': catalog.active_id(conn)}

    def import_package(self, body):
        from app.knowledge.packages import import_package
        with self.database.session(write=True,library_write=True) as conn:
            return import_package(conn, body['package'], trusted_sha256=body['trusted_sha256'],
                                  expected_parent=body['expected_active_release_id'], confirmed=body['confirmed'])

    def activate_package(self, body):
        from app.knowledge.packages import activate_package
        with self.database.session(write=True,library_write=True) as conn:
            return activate_package(conn, body['sha256'], expected_current=body['expected_active_release_id'],
                                    confirmed=body['confirmed'])

    def packages(self):
        from app.storage.catalog_packages import listing
        with self.database.session() as conn:
            return {'packages': listing(conn), 'current_release_id': catalog.active_id(conn)}
