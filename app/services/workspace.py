"""Read models for the workspace; this module has no web-framework dependency."""
import sqlite3
from copy import deepcopy
from threading import Lock
from app.common import rows,json_load
from app.bank.access import public_bank,preferences
from app.learning.loop import loop_snapshot

def enrich_question(item: dict) -> dict:
    item["fingerprint"] = json_load(item.pop("fingerprint_json", None), {})
    item["regions"] = json_load(item.pop("regions_json", None), [])
    return item

def build_profile(conn: sqlite3.Connection) -> dict:
    stage_names = ["题目切入", "建模与路径", "中间计算", "最终处理", "时间与审题"]
    stage = {name: {"state": "未验证", "evidence": 0, "failures": 0, "successes": 0} for name in stage_names}
    for q in rows(conn, "SELECT q.error_stage,q.review_status,q.correctness FROM questions q JOIN papers p ON p.id=q.paper_id WHERE p.archived_at IS NULL"):
        if q["error_stage"]:
            stage[q["error_stage"]] = stage.get(q["error_stage"], {"state":"未验证","evidence":0,"failures":0,"successes":0})
            stage[q["error_stage"]]["evidence"] += 1
            if q["correctness"] == "wrong":
                stage[q["error_stage"]]["failures"] += 1
            if q["review_status"] in ("已掌握", "已复盘"):
                stage[q["error_stage"]]["successes"] += 1
    for name, info in stage.items():
        if info["failures"] >= 3:
            info["state"] = "重复失分"
        elif info["failures"] and info["successes"]:
            info["state"] = "不稳定"
        elif info["successes"]:
            info["state"] = "基本掌握"
    repeated = rows(conn, """SELECT q.error_type AS label, COUNT(*) AS count FROM questions q JOIN papers p ON p.id=q.paper_id
                            WHERE p.archived_at IS NULL AND q.error_type IS NOT NULL AND q.error_type != ''
                            GROUP BY q.error_type ORDER BY count DESC LIMIT 5""")
    return {"stages": stage, "repeated_errors": repeated}

class WorkspaceService:
    def __init__(self,config,database):
        self.config,self.database=config,database
        self._lock=Lock()
        self._observers=[]
        self._revision=None
        self._bootstrap=None

    def close(self):
        with self._lock:
            for conn in self._observers:conn.close()
            self._observers=[]
            self._revision=None
            self._bootstrap=None

    def _data_revision(self):
        # data_version is comparable only on the SAME connection. Keep read-only
        # observers alive, with no read transaction held between requests. Every
        # writer (including another process and WAL commits) invalidates the cache.
        if not self._observers:
            try:
                for path in (self.config.database,self.config.library_database):
                    self._observers.append(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',
                                                          uri=True,check_same_thread=False))
            except BaseException:
                for conn in self._observers:conn.close()
                self._observers=[]
                raise
        return tuple(conn.execute('PRAGMA data_version').fetchone()[0] for conn in self._observers)

    def bootstrap(self):
        with self._lock:
            revision=self._data_revision()
            if self._bootstrap is not None and revision==self._revision:
                return deepcopy(self._bootstrap)
            value=self._build_bootstrap()
            # A commit during the build must never label old/mixed reads with a
            # newer revision. Return this read as before, but rebuild next time.
            if revision==self._data_revision():
                self._bootstrap=value
                self._revision=revision
            else:
                self._bootstrap=None
                self._revision=None
            return deepcopy(value)

    def revision(self):
        with self._lock:
            return self._data_revision()

    def _build_bootstrap(self):
        with self.database.session() as conn:
            papers=rows(conn,'SELECT * FROM papers ORDER BY COALESCE(exam_date,created_at) DESC,created_at DESC')
            questions=[enrich_question(q) for q in rows(conn,'SELECT * FROM questions ORDER BY created_at DESC')]
            bank=[public_bank(conn,r[0],view='library') for r in conn.execute("SELECT id FROM bank_questions WHERE source!='本地示例题库' ORDER BY id")]
            settings=preferences(conn);profile=build_profile(conn);loop=loop_snapshot(conn)
        if not self.config.demo:
            papers=[p for p in papers if not p['id'].startswith('paper-demo-')]
            ids={p['id'] for p in papers};questions=[q for q in questions if q['paper_id'] in ids]
        return dict(papers=papers,questions=questions,bank=bank,profile=profile,loop=loop,preferences=settings)
    def papers(self,archived='0'):
        where=' WHERE archived_at IS NOT NULL' if archived=='1' else '' if archived=='all' else ' WHERE archived_at IS NULL'
        order='archived_at DESC' if archived=='1' else 'COALESCE(exam_date,created_at) DESC,created_at DESC'
        with self.database.session() as conn:return {'papers':rows(conn,'SELECT * FROM papers'+where+' ORDER BY '+order)}
    def loop(self):
        with self.database.session() as conn:return loop_snapshot(conn)
    def profile(self):
        with self.database.session() as conn:return build_profile(conn)
    def versions(self):
        with self.database.session() as conn:return {'versions':rows(conn,'SELECT * FROM record_versions ORDER BY created_at DESC LIMIT 100'),'reports':rows(conn,'SELECT id,paper_id,created_at FROM agent_reports ORDER BY created_at DESC LIMIT 100')}
