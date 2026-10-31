"""Small consistent read models; release the learner DB before file validation.

Copy exact rows/rowids needed by knowledge navigation, excluding large unrelated
preparation-task inputs and tool history. This is an ephemeral query-only SQLite
snapshot, never a restored learner database or a second execution identity.
"""
from contextlib import contextmanager,closing
import sqlite3
from app.knowledge.catalog import atomic
from app.storage.boundaries import schema_rows

TABLES=('bank_questions','bank_resources','bank_identity','bank_links','bank_identity_reviews',
        'bank_views','bank_cross_reviews','preferences','question_annotations','question_annotation_links',
        'question_annotation_topics','prepared_annotation_ids','imported_question_annotations',
        'imported_annotation_topics','annotation_cache_packages','annotation_cache_state',
        'knowledge_nodes','knowledge_mappings','knowledge_mapping_versions',
        'knowledge_catalog_state','knowledge_catalog_releases','knowledge_catalog_nodes','knowledge_catalog_redirects',
        'papers','questions','question_diagnoses','agent_reports','diagnostic_probes','probe_attempts',
        'learning_events','retired_probes','record_versions','learning_results','learning_tasks',
        'practice_plan_members','practice_deferred_probes','paper_question_bindings','annotation_provenance')

FILTERS={
    'knowledge_catalog_releases':'id IN (SELECT release_id FROM knowledge_catalog_state)',
    'knowledge_catalog_nodes':'release_id IN (SELECT release_id FROM knowledge_catalog_state)',
    'knowledge_catalog_redirects':'release_id IN (SELECT release_id FROM knowledge_catalog_state)',
    'record_versions':"kind='attempt'",
    'learning_results':"kind='prepare_practice'",
    'learning_tasks':"id IN (SELECT task_id FROM learning_results WHERE kind='prepare_practice')",
}


@contextmanager
def navigation_snapshot(database):
    with closing(sqlite3.connect(':memory:')) as target:
        target.row_factory=sqlite3.Row
        with database.session() as source, atomic(source):
            schemas={r['name']:r['sql'] for r in schema_rows(source)}
            copied=[]
            for table in TABLES:
                if table not in schemas:continue
                target.execute(schemas[table]);copied.append(table)
                query='SELECT rowid,* FROM '+table
                if table in FILTERS:query+=' WHERE '+FILTERS[table]
                cursor=source.execute(query+' ORDER BY rowid')
                columns=[r[0] for r in cursor.description]
                quoted=','.join('"'+c.replace('"','""')+'"' for c in columns)
                insert='INSERT INTO '+table+'('+quoted+') VALUES('+','.join('?' for _ in columns)+')'
                while rows:=cursor.fetchmany(256):target.executemany(insert,rows)
            for table in copied:
                for row in schema_rows(source,'index'):
                    if row['tbl_name']!=table or not row['sql']:continue
                    target.execute(row['sql'])
            target.commit()
        # No original DB handle or shared lock survives this point.
        target.execute('PRAGMA query_only=ON')
        with atomic(target):yield target
