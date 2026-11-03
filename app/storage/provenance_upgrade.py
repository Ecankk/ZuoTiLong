"""Explicit preview/confirm backfill from a read-only execution workspace."""
from contextlib import contextmanager
import json,sqlite3
from pathlib import Path
from app.knowledge import catalog
from app.storage.provenance import SCHEMA,capture_provenance,validate_proof


@contextmanager
def connection(library, source_database, *, write=False):
    path=Path(library).resolve()/'library.db'
    conn=sqlite3.connect(path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=15)
    conn.row_factory=sqlite3.Row
    try:
        conn.execute('ATTACH DATABASE ? AS origin',(Path(source_database).resolve().as_uri()+'?mode=ro',))
        conn.execute('BEGIN')
        yield conn
    finally:conn.close()


def _plan(conn):
    annotations=list(conn.execute('SELECT * FROM question_annotations ORDER BY id'))
    previous={r['annotation_id']:r['payload_json'] for r in conn.execute('SELECT * FROM annotation_provenance')}
    changes=[];unchanged=[];blocked=[];proposals={}
    for annotation in annotations:
        aid=annotation['id']
        try:
            prior=json.loads(previous[aid]) if aid in previous else None
            if prior is not None and prior.get('schema')==SCHEMA:
                if not validate_proof(annotation,prior):raise ValueError('既有v2出处未发布，不能自动发布')
                unchanged.append(aid);continue
            value=capture_provenance(conn,annotation)
            if prior is not None:
                if not validate_proof(annotation,prior):raise ValueError('既有出处未发布，不能自动发布')
                if any(prior.get(key)!=value[key] for key in ('published','rule_revision','source','analysis_sha256','reviewed_roles','result_sha256')):
                    raise ValueError('既有出处与原执行证据冲突，不能覆盖')
            proposals[aid]=value
            changes.append(dict(annotation_id=aid,action='upgrade' if prior else 'add',evidence_sha256=value['evidence_sha256']))
        except (ValueError,KeyError,TypeError) as exc:
            blocked.append(dict(annotation_id=aid,reason=str(exc)))
    state=dict(annotations=[dict(a) for a in annotations],previous=previous,changes=changes,unchanged=unchanged,blocked=blocked)
    report=dict(schema=SCHEMA,total=len(annotations),changes=changes,unchanged=unchanged,blocked=blocked,
                counts=dict(changes=len(changes),unchanged=len(unchanged),blocked=len(blocked)),plan_sha256=catalog.digest(state))
    return report,proposals


def upgrade(library, source_database, *, confirm=None):
    library=Path(library).resolve();source_database=Path(source_database).resolve()
    if source_database==library/'library.db':raise ValueError('来源必须为旧工作区数据库，不能是通用库自身')
    with connection(library,source_database) as conn:report,_=_plan(conn)
    if confirm is None:return dict(report,applied=False)
    if confirm!=report['plan_sha256']:raise ValueError('预演已变化，请重新预演并确认 plan_sha256')
    if report['blocked']:raise ValueError('仍有无法验证的出处，未写入；请先处理预演报告')
    if not report['changes']:return dict(report,applied=False,backup=None)
    from app.storage.library_backup import backup_library
    backup=backup_library(library,workspaces=[source_database.parent])
    with connection(library,source_database,write=True) as conn:
        current,proposals=_plan(conn)
        if current['plan_sha256']!=confirm:raise ValueError('备份期间原证据或目标已变化，请重新预演')
        for aid,value in proposals.items():
            conn.execute('''INSERT INTO annotation_provenance VALUES(?,?)
                ON CONFLICT(annotation_id) DO UPDATE SET payload_json=excluded.payload_json''',(aid,catalog.encode(value)))
        conn.commit()
    return dict(report,applied=True,backup=backup)
