"""Read models for the workspace; this module has no web-framework dependency."""
import sqlite3
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
    def __init__(self,config,database):self.config,self.database=config,database
    def bootstrap(self):
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
