from __future__ import annotations

import cgi
import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
DATA = ROOT / ".mathlens"
PAPERS_DIR = DATA / "papers"
DB_PATH = DATA / "mathlens.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    PAPERS_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def as_json(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def json_load(value, fallback=None):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def init_db() -> None:
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            exam_date TEXT,
            score REAL DEFAULT 0,
            total_score REAL DEFAULT 150,
            duration INTEGER,
            source_name TEXT,
            source_path TEXT,
            import_status TEXT DEFAULT 'needs_review',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            number TEXT NOT NULL,
            subject TEXT DEFAULT '数学一',
            stem TEXT,
            score_earned REAL DEFAULT 0,
            max_score REAL DEFAULT 0,
            correctness TEXT DEFAULT 'unknown',
            review_status TEXT DEFAULT '待诊断',
            error_stage TEXT,
            error_type TEXT,
            knowledge TEXT,
            fingerprint_json TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bank_questions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_ref TEXT,
            stem TEXT NOT NULL,
            answer TEXT,
            explanation TEXT,
            tags_json TEXT,
            fingerprint_json TEXT,
            difficulty INTEGER DEFAULT 3,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id TEXT PRIMARY KEY,
            question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            bank_question_id TEXT REFERENCES bank_questions(id) ON DELETE SET NULL,
            mode TEXT DEFAULT '检验',
            correct INTEGER DEFAULT 0,
            score REAL DEFAULT 0,
            elapsed INTEGER,
            confidence INTEGER,
            error_stage TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_questions_paper ON questions(paper_id);
        CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(review_status);
        CREATE INDEX IF NOT EXISTS idx_bank_source ON bank_questions(source);
        """
    )
    if conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0:
        seed(conn)
    conn.commit()
    conn.close()


def seed(conn: sqlite3.Connection) -> None:
    created = now_iso()
    papers = [
        ("paper-demo-2022", "真题 2022（示例）", "2026-10-21", 101, 150, 136, "真题2022.pdf", "needs_review"),
        ("paper-demo-2021", "真题 2021（示例）", "2026-10-17", 96, 150, 142, "真题2021.pdf", "analyzed"),
    ]
    conn.executemany(
        "INSERT INTO papers(id,title,exam_date,score,total_score,duration,source_name,import_status,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        [p + (created,) for p in papers],
    )
    questions = [
        ("q-demo-01", "paper-demo-2022", "18", "高数", "含参数定积分的换元与上下限处理", 4, 5, "partial", "待诊断", None, None, "定积分｜换元｜上下限联动", json.dumps({"objects":["定积分"],"entry_cues":["复合函数"],"method":["换元积分"],"operations":["上下限同步变换"],"final_checks":["符号","上下限"]}, ensure_ascii=False), "做出了主体步骤，但换元后上下限漏改", created),
        ("q-demo-02", "paper-demo-2022", "19", "线代", "二次型正定性与正交变换", 2, 5, "wrong", "待诊断", None, None, "二次型｜特征值｜正定性", json.dumps({"objects":["二次型","特征值"],"entry_cues":["正定"],"method":["特征值判断"],"operations":["矩阵运算"],"final_checks":["特征值符号"]}, ensure_ascii=False), "不会从题目条件判断切入方法", created),
        ("q-demo-03", "paper-demo-2022", "20", "概率", "分布函数与数字特征", 5, 5, "correct", "高风险正确", None, None, "分布函数｜数字特征", json.dumps({"objects":["分布函数"],"entry_cues":["分段分布"],"method":["数字特征公式"],"operations":["分段积分"],"final_checks":["定义域"]}, ensure_ascii=False), "答对但用时 18 分钟且自信度低", created),
        ("q-demo-04", "paper-demo-2021", "17", "高数", "多元函数极值的条件判断", 0, 5, "wrong", "已复盘", "建模与路径", "方法不会", "多元函数｜极值｜条件判断", json.dumps({"objects":["多元函数极值"],"entry_cues":["约束条件"],"method":["拉格朗日乘子"],"operations":["方程组"],"final_checks":["候选点筛选"]}, ensure_ascii=False), "忽略了约束条件", created),
        ("q-demo-05", "paper-demo-2021", "22", "概率", "二维随机变量边缘分布", 3, 5, "partial", "训练中", "中间计算", "计算失误", "二维随机变量｜边缘分布", json.dumps({"objects":["二维随机变量"],"entry_cues":["联合分布"],"method":["边缘化"],"operations":["积分区间"],"final_checks":["区域边界"]}, ensure_ascii=False), "积分区域边界漏项", created),
    ]
    conn.executemany(
        """INSERT INTO questions(id,paper_id,number,subject,stem,score_earned,max_score,correctness,review_status,error_stage,error_type,knowledge,fingerprint_json,notes,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        questions,
    )
    bank = [
        ("bank-calc-01", "本地示例题库", "calc-01", "定积分换元：给定复合函数，判断换元变量与上下限", "按新变量同步修改上下限", "先写换元关系，再检查上下限与符号。", ["定积分","换元","上下限联动"], {"objects":["定积分"],"method":["换元积分"],"stages":["切入","计算"]}, 2),
        ("bank-calc-02", "本地示例题库", "calc-02", "参数积分：换元后保留参数并判断积分区间", "分情况讨论参数范围", "关键是先确定变量范围，再写积分上下限。", ["定积分","参数","换元"], {"objects":["定积分"],"method":["换元积分"],"stages":["切入","最终处理"]}, 3),
        ("bank-calc-03", "本地示例题库", "calc-03", "积分区域变换：用极坐标计算二重积分", "先画区域再换元", "区域边界决定上下限，不能直接套公式。", ["重积分","换元","区域"], {"objects":["重积分"],"method":["极坐标"],"stages":["建模","计算"]}, 3),
        ("bank-linear-01", "本地示例题库", "linear-01", "二次型正定性：由特征值符号判断", "所有特征值为正", "先识别正定性，再选择顺序主子式或特征值。", ["二次型","特征值","正定性"], {"objects":["二次型"],"method":["特征值判断"],"stages":["切入","最终处理"]}, 2),
        ("bank-linear-02", "本地示例题库", "linear-02", "二次型正交变换：构造标准形", "正交矩阵列为单位特征向量", "注意特征向量的单位化和顺序。", ["二次型","正交变换"], {"objects":["二次型"],"method":["正交变换"],"stages":["建模","中间计算"]}, 3),
        ("bank-linear-03", "本地示例题库", "linear-03", "含参数矩阵的特征值判断", "按参数范围讨论", "参数变化会改变正定性结论。", ["特征值","参数","正定性"], {"objects":["特征值"],"method":["特征值判断"],"stages":["切入","最终处理"]}, 4),
        ("bank-prob-01", "本地示例题库", "prob-01", "已知分布函数求概率与密度", "先分段再积分", "先写定义域和连续性边界。", ["分布函数","密度"], {"objects":["分布函数"],"method":["分段积分"],"stages":["切入","最终处理"]}, 2),
        ("bank-prob-02", "本地示例题库", "prob-02", "联合密度求边缘密度", "对另一变量积分", "先画积分区域，避免漏掉边界。", ["二维随机变量","边缘分布"], {"objects":["二维随机变量"],"method":["边缘化"],"stages":["建模","中间计算"]}, 3),
        ("bank-prob-03", "本地示例题库", "prob-03", "数字特征综合计算", "分别计算期望与方差", "注意方差平方项和分布范围。", ["数字特征","期望","方差"], {"objects":["数字特征"],"method":["数字特征公式"],"stages":["中间计算","最终处理"]}, 2),
        ("bank-calc-04", "本地示例题库", "calc-04", "中值定理：判断可用条件并定位结论", "先核对闭区间连续与开区间可导", "条件不完整时不能直接套结论。", ["中值定理","条件判断"], {"objects":["中值定理"],"method":["条件判断"],"stages":["切入","最终处理"]}, 2),
    ]
    conn.executemany(
        """INSERT INTO bank_questions(id,source,source_ref,stem,answer,explanation,tags_json,fingerprint_json,difficulty,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [(a,b,c,d,e,f,json.dumps(g,ensure_ascii=False),json.dumps(h,ensure_ascii=False),i,created) for a,b,c,d,e,f,g,h,i in bank],
    )


def rows(conn, sql: str, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def enrich_question(item: dict) -> dict:
    item["fingerprint"] = json_load(item.pop("fingerprint_json", None), {})
    return item


def bootstrap() -> dict:
    conn = connect()
    papers = rows(conn, "SELECT * FROM papers ORDER BY exam_date DESC, created_at DESC")
    questions = [enrich_question(q) for q in rows(conn, "SELECT * FROM questions ORDER BY created_at DESC")]
    bank = []
    for q in rows(conn, "SELECT * FROM bank_questions ORDER BY created_at DESC"):
        q["tags"] = json_load(q.pop("tags_json", None), [])
        q["fingerprint"] = json_load(q.pop("fingerprint_json", None), {})
        bank.append(q)
    profile = build_profile(conn)
    conn.close()
    return {"papers": papers, "questions": questions, "bank": bank, "profile": profile}


def build_profile(conn: sqlite3.Connection) -> dict:
    stage_names = ["题目切入", "建模与路径", "中间计算", "最终处理", "时间与审题"]
    stage = {name: {"state": "未验证", "evidence": 0, "failures": 0, "successes": 0} for name in stage_names}
    for q in rows(conn, "SELECT error_stage, review_status, correctness FROM questions"):
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
    repeated = rows(conn, """SELECT error_type AS label, COUNT(*) AS count FROM questions
                            WHERE error_type IS NOT NULL AND error_type != ''
                            GROUP BY error_type ORDER BY count DESC LIMIT 5""")
    return {"stages": stage, "repeated_errors": repeated}


class Handler(BaseHTTPRequestHandler):
    server_version = "MathLens/0.1"

    def log_message(self, fmt, *args):
        print("[mathlens] " + fmt % args)

    def send_json(self, payload, status=HTTPStatus.OK):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.api_get(parsed)
            return
        self.static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.api_post(parsed)
            return
        self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def static(self, path):
        rel = path.lstrip("/") or "index.html"
        candidate = (DIST / rel).resolve()
        if DIST not in candidate.parents and candidate != DIST:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.exists() or not candidate.is_file():
            candidate = DIST / "index.html"
        content_type = "text/html; charset=utf-8"
        if candidate.suffix == ".css": content_type = "text/css; charset=utf-8"
        if candidate.suffix == ".js": content_type = "application/javascript; charset=utf-8"
        if candidate.suffix == ".json": content_type = "application/json; charset=utf-8"
        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def api_get(self, parsed):
        conn = connect()
        try:
            if parsed.path == "/api/health":
                self.send_json({"ok": True, "version": "0.1.0"})
            elif parsed.path == "/api/bootstrap":
                self.send_json(bootstrap())
            elif parsed.path == "/api/profile":
                self.send_json(build_profile(conn))
            elif parsed.path == "/api/papers":
                self.send_json({"papers": rows(conn, "SELECT * FROM papers ORDER BY exam_date DESC, created_at DESC")})
            elif parsed.path == "/api/bank":
                query = parse_qs(parsed.query)
                text = (query.get("q", [""])[0] or "").strip().lower()
                stage = (query.get("stage", [""])[0] or "").strip()
                bank = []
                for q in rows(conn, "SELECT * FROM bank_questions ORDER BY difficulty, created_at DESC"):
                    tags = json_load(q["tags_json"], [])
                    fp = json_load(q["fingerprint_json"], {})
                    blob = " ".join([q["stem"], q["source"], " ".join(tags), json.dumps(fp, ensure_ascii=False)]).lower()
                    if text and text not in blob:
                        continue
                    if stage and stage not in fp.get("stages", []):
                        continue
                    q["tags"] = tags
                    q["fingerprint"] = fp
                    q.pop("tags_json", None); q.pop("fingerprint_json", None)
                    bank.append(q)
                self.send_json({"bank": bank[:30]})
            else:
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        finally:
            conn.close()

    def api_post(self, parsed):
        if parsed.path == "/api/papers/import":
            self.import_paper()
            return
        conn = connect()
        try:
            if parsed.path == "/api/papers":
                body = self.read_json()
                paper_id = "paper-" + uuid.uuid4().hex[:10]
                conn.execute("INSERT INTO papers(id,title,exam_date,score,total_score,duration,source_name,import_status,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                             (paper_id, body.get("title") or "未命名试卷", body.get("exam_date"), float(body.get("score") or 0), float(body.get("total_score") or 150), int(body.get("duration") or 0), body.get("source_name"), "needs_review", now_iso()))
                conn.commit()
                self.send_json({"paper": as_json(conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone())}, HTTPStatus.CREATED)
            elif parsed.path.startswith("/api/papers/") and parsed.path.endswith("/confirm"):
                paper_id = parsed.path.split("/")[3]
                body = self.read_json()
                numbers = [str(x).strip() for x in body.get("numbers", []) if str(x).strip()]
                scores = body.get("scores", [])
                if not numbers:
                    self.send_json({"error": "至少需要一个题号"}, HTTPStatus.BAD_REQUEST)
                    return
                existing = conn.execute("SELECT COUNT(*) FROM questions WHERE paper_id=?", (paper_id,)).fetchone()[0]
                if existing:
                    self.send_json({"error": "这张试卷已经有题目记录"}, HTTPStatus.CONFLICT)
                    return
                created = now_iso()
                for idx, number in enumerate(numbers):
                    raw_score = scores[idx] if idx < len(scores) else (scores[0] if scores else 0)
                    try: max_score = float(raw_score or 0)
                    except (TypeError, ValueError): max_score = 0
                    qid = f"{paper_id}-q-{idx+1:02d}"
                    conn.execute("INSERT INTO questions(id,paper_id,number,subject,stem,max_score,correctness,review_status,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                                 (qid, paper_id, number, body.get("subject") or "数学一", f"第 {number} 题（待补充题干）", max_score, "unknown", "待诊断", created))
                conn.execute("UPDATE papers SET import_status='analyzed' WHERE id=?", (paper_id,))
                conn.commit()
                self.send_json({"paper_id": paper_id, "created_questions": len(numbers), "status": "analyzed"}, HTTPStatus.CREATED)
            elif parsed.path.startswith("/api/questions/") and parsed.path.endswith("/diagnose"):
                question_id = parsed.path.split("/")[3]
                body = self.read_json()
                fields = {k: body.get(k) for k in ["review_status","error_stage","error_type","knowledge","notes"] if k in body}
                if fields:
                    clause = ", ".join(f"{k}=?" for k in fields)
                    conn.execute(f"UPDATE questions SET {clause} WHERE id=?", tuple(fields.values()) + (question_id,))
                    conn.commit()
                self.send_json({"question": as_json(conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()), "profile": build_profile(conn)})
            elif parsed.path == "/api/reviews":
                body = self.read_json()
                review_id = "review-" + uuid.uuid4().hex[:10]
                conn.execute("INSERT INTO reviews(id,question_id,bank_question_id,mode,correct,score,elapsed,confidence,error_stage,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (review_id, body.get("question_id"), body.get("bank_question_id"), body.get("mode") or "检验", int(bool(body.get("correct"))), float(body.get("score") or 0), int(body.get("elapsed") or 0), int(body.get("confidence") or 0), body.get("error_stage"), body.get("notes"), now_iso()))
                if body.get("correct"):
                    conn.execute("UPDATE questions SET review_status=? WHERE id=?", ("已掌握" if body.get("transfer") else "训练中", body.get("question_id")))
                else:
                    conn.execute("UPDATE questions SET review_status=?, error_stage=COALESCE(?, error_stage) WHERE id=?", ("不稳定", body.get("error_stage"), body.get("question_id")))
                conn.commit()
                self.send_json({"review_id": review_id, "profile": build_profile(conn) }, HTTPStatus.CREATED)
            elif parsed.path == "/api/bank/import":
                body = self.read_json()
                incoming = body if isinstance(body, list) else body.get("questions", [])
                count = 0
                for item in incoming:
                    qid = item.get("id") or "bank-" + uuid.uuid4().hex[:10]
                    stem = item.get("stem") or item.get("content") or item.get("question") or ""
                    tags = item.get("tags") or item.get("keywords") or ([item.get("chapter")] if item.get("chapter") else [])
                    conn.execute("INSERT OR REPLACE INTO bank_questions(id,source,source_ref,stem,answer,explanation,tags_json,fingerprint_json,difficulty,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (qid, item.get("source") or "本地题库", item.get("source_ref") or item.get("uid") or item.get("id"), stem, item.get("answer") or item.get("solution"), item.get("explanation") or item.get("analysis"), json.dumps(tags, ensure_ascii=False), json.dumps(item.get("fingerprint", {}), ensure_ascii=False), int(item.get("difficulty") or 3), now_iso()))
                    count += 1
                conn.commit()
                self.send_json({"imported": count}, HTTPStatus.CREATED)
            else:
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        finally:
            conn.close()

    def import_paper(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_json({"error": "multipart/form-data required"}, HTTPStatus.BAD_REQUEST)
            return
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD":"POST", "CONTENT_TYPE":content_type})
        upload = form["file"] if "file" in form else None
        if upload is None or not getattr(upload, "filename", None):
            self.send_json({"error": "file required"}, HTTPStatus.BAD_REQUEST)
            return
        paper_id = "paper-" + uuid.uuid4().hex[:10]
        filename = Path(upload.filename).name
        target_dir = PAPERS_DIR / paper_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        with target.open("wb") as fh:
            shutil.copyfileobj(upload.file, fh)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        title = form.getfirst("title") or Path(filename).stem
        exam_date = form.getfirst("exam_date") or date.today().isoformat()
        conn = connect()
        conn.execute("INSERT INTO papers(id,title,exam_date,source_name,source_path,import_status,created_at) VALUES (?,?,?,?,?,?,?)",
                     (paper_id, title, exam_date, filename, str(target.relative_to(ROOT)), "needs_review", now_iso()))
        conn.commit()
        paper = as_json(conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone())
        conn.close()
        self.send_json({"paper": paper, "sha256": digest, "next": "确认题目切分并录入得分"}, HTTPStatus.CREATED)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MathLens local-first paper diagnosis server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()
    init_db()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"MathLens running at http://{args.host}:{args.port}/")
    print(f"Data directory: {DATA}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
