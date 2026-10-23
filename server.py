from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import sqlite3
import uuid
import socket
from email.parser import BytesParser
from email.policy import default as email_policy
from datetime import date, datetime, timezone
from contextlib import closing
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pdf_pipeline import extract_pdf, match_bank_questions
from learning_loop import init_loop, loop_snapshot, submit_probe, apply_report, supplement_attempt, revise_assessment, replace_probe
from bank_access import preferences, save_preferences, public_bank, require_access, reveal, init_access, record_view
from codex_bridge import CodexBridge, BridgeConflict
from answer_images import save_answer_image, image_records, image_path
from local_maintenance import backup,cleanup_images,restore
from mobile_upload import MobileInbox
from server_runtime import VERSION, data_identity, bind_server, publish_address, clear_address
from contextlib import contextmanager


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
DATA = Path(os.environ.get("MATHLENS_DATA_DIR", str(ROOT / ".mathlens"))).resolve()
PAPERS_DIR = DATA / "papers"
DB_PATH = DATA / "mathlens.db"
BRIDGE = None
MOBILE = None

@contextmanager
def mobile_guard():
    if BRIDGE:
        with BRIDGE.lock:
            BRIDGE.assert_user_write_allowed();yield
    else:yield


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
    # Keep the first version's SQLite database usable while adding source
    # evidence incrementally. SQLite has no IF NOT EXISTS for columns.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(papers)")}
    for name, definition in {
        "page_count": "INTEGER DEFAULT 0",
        "analysis_engine": "TEXT",
        "analysis_message": "TEXT",
        "analyzed_at": "TEXT",
    }.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE papers ADD COLUMN {name} {definition}")
    question_columns = {row["name"] for row in conn.execute("PRAGMA table_info(questions)")}
    for name, definition in {
        "page_start": "INTEGER",
        "page_end": "INTEGER",
        "bbox_json": "TEXT",
        "ocr_confidence": "REAL",
        "match_bank_id": "TEXT",
        "match_score": "REAL",
        "source_text": "TEXT",
    }.items():
        if name not in question_columns:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {name} {definition}")
    init_loop(conn)
    if os.environ.get("MATHLENS_DEMO") == "1" and conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0:
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
    item["regions"] = json_load(item.pop("regions_json", None), [])
    return item


def bootstrap() -> dict:
    conn = connect()
    papers = rows(conn, "SELECT * FROM papers ORDER BY exam_date DESC, created_at DESC")
    questions = [enrich_question(q) for q in rows(conn, "SELECT * FROM questions ORDER BY created_at DESC")]
    bank = [public_bank(conn,r[0],view='library') for r in conn.execute("SELECT id FROM bank_questions WHERE source!='本地示例题库' ORDER BY id")]
    settings=preferences(conn)
    profile = build_profile(conn)
    if os.environ.get("MATHLENS_DEMO") != "1":
        papers = [p for p in papers if not p["id"].startswith("paper-demo-")]
        visible_ids = {p["id"] for p in papers}
        questions = [q for q in questions if q["paper_id"] in visible_ids]
    conn.close()
    conn = connect()
    loop = loop_snapshot(conn)
    conn.close()
    return {"papers": papers, "questions": questions, "bank": bank, "profile": profile, "loop": loop,'preferences':settings}


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


def analyze_paper_record(conn: sqlite3.Connection, paper_id: str) -> dict:
    paper = as_json(conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone())
    if not paper:
        raise ValueError("试卷不存在")
    source_path = paper.get("source_path")
    if not source_path:
        raise ValueError("这张试卷没有本地 PDF 文件")
    pdf_path = (ROOT / source_path).resolve()
    if PAPERS_DIR not in pdf_path.parents or not pdf_path.is_file():
        raise ValueError("试卷文件不在本地资料目录中")

    bank_rows = []
    for item in rows(conn, "SELECT * FROM bank_questions"):
        item["tags"] = json_load(item.pop("tags_json", None), [])
        item["fingerprint"] = json_load(item.pop("fingerprint_json", None), {})
        bank_rows.append(item)
    result = extract_pdf(pdf_path)
    extracted = match_bank_questions(result["questions"], bank_rows)
    existing = rows(conn, "SELECT * FROM questions WHERE paper_id=? ORDER BY created_at", (paper_id,))
    created = now_iso()
    for index, item in enumerate(extracted):
        old = next((row for row in existing if str(row.get("number")) == str(item["number"])), None)
        if old is None and index < len(existing) and "待补充题干" in (existing[index].get("stem") or ""):
            old = existing[index]
        qid = old["id"] if old else f"{paper_id}-q-{index + 1:02d}"
        values = (
            item["number"],
            item["stem"],
            json.dumps(item.get("fingerprint") or {}, ensure_ascii=False),
            item.get("knowledge") or (old.get("knowledge") if old else None),
            item.get("page_start"),
            item.get("page_end"),
            json.dumps(item.get("bbox"), ensure_ascii=False) if item.get("bbox") else None,
            item.get("ocr_confidence", 0),
            item.get("match_bank_id"),
            item.get("match_score", 0),
            item["stem"],
        )
        if old and old["id"] == qid:
            if conn.execute("SELECT question_id FROM question_diagnoses WHERE question_id=?", (qid,)).fetchone():
                continue  # Re-extraction must not overwrite an Agent-reviewed attempt.
            conn.execute(
                """UPDATE questions SET number=?, stem=?, fingerprint_json=?, knowledge=?, page_start=?, page_end=?,
                   bbox_json=?, ocr_confidence=?, match_bank_id=?, match_score=?, source_text=? WHERE id=?""",
                values + (qid,),
            )
        else:
            conn.execute(
                """INSERT INTO questions(id,paper_id,number,subject,stem,score_earned,max_score,correctness,review_status,
                   knowledge,fingerprint_json,page_start,page_end,bbox_json,ocr_confidence,match_bank_id,match_score,source_text,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (qid, paper_id, item["number"], "数学一", item["stem"], 0, 0, "unknown", "待诊断",
                 item.get("knowledge"), values[2], item.get("page_start"), item.get("page_end"), values[6],
                 item.get("ocr_confidence", 0), item.get("match_bank_id"), item.get("match_score", 0), item["stem"], created),
            )
        conn.execute("UPDATE questions SET regions_json=? WHERE id=?", (json.dumps(item.get("regions", []), ensure_ascii=False), qid))
    has_report = conn.execute("SELECT id FROM agent_reports WHERE paper_id=?", (paper_id,)).fetchone()
    status = "diagnosed" if has_report else "segmented" if result.get("complete") else "needs_review"
    conn.execute(
        "UPDATE papers SET import_status=?, page_count=?, analysis_engine=?, analysis_message=?, analyzed_at=? WHERE id=?",
        (status, len(result["pages"]), result["engine"], result["message"], created, paper_id),
    )
    conn.commit()
    task_dir = DATA / "tasks" / paper_id
    task_dir.mkdir(parents=True, exist_ok=True)
    page_images = []
    import pymupdf as fitz
    with fitz.open(str(pdf_path)) as document:
        for idx, page in enumerate(document):
            target = task_dir / f"page-{idx+1:02d}.png"
            if not target.is_file():
                page.get_pixmap(matrix=fitz.Matrix(1.8,1.8), alpha=False).save(str(target))
            page_images.append(str(target))
    request = {"paper_id":paper_id,"source_sha256":result["source_sha256"],"source_pdf":str(pdf_path),
               "page_images":page_images,"questions":extracted,"status":"report_available" if has_report else "awaiting_agent",
               "instructions":"Read original pages and work, verify OCR against images. Submit evidence-backed report via scripts/agent_tasks.py apply. Do not invent probe results, scores or causes. See docs/agent-workflow.md."}
    task_file = task_dir / "request.json"
    task_file.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding="utf-8")
    return {
        "paper": as_json(conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()),
        "questions": rows(conn, "SELECT * FROM questions WHERE paper_id=? ORDER BY number", (paper_id,)),
        "engine": result["engine"],
        "message": result["message"],
        "warnings": result["warnings"],
        "created_questions": len(extracted),
        "agent_task": str(task_file),
    }


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

    def send_file(self, path: Path, content_type: str):
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

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
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if urlparse("http://" + host).hostname not in ("127.0.0.1", "localhost", "::1") or (origin and origin != "http://" + host):
            self.send_json({"error": "只接受本地网页的同源请求"}, HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            try:
                if parsed.path.startswith("/api/agent/"):
                    self.agent_post(parsed)
                elif parsed.path in ('/api/screen','/api/drafts','/api/mobile-upload/stop') or parsed.path.endswith('/reveal'):
                    self.api_post(parsed)
                elif BRIDGE:
                    with BRIDGE.lock:
                        BRIDGE.assert_user_write_allowed()
                        self.api_post(parsed)
                else:
                    self.api_post(parsed)
            except BridgeConflict as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            except (ValueError, RuntimeError, TimeoutError) as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
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
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if candidate.suffix == ".html": content_type = "text/html; charset=utf-8"
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
        if parsed.path.startswith('/api/answer-images/'):
            try:
                with closing(connect()) as conn:
                    record = image_records(conn, [parsed.path.rsplit('/',1)[-1]])[0]
                self.send_file(image_path(record, DATA), 'image/jpeg')
            except ValueError as exc:
                self.send_json({'error':str(exc)}, HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/api/agent/state":
            self.send_json(BRIDGE.snapshot() if BRIDGE else {"connected": False, "status": "disconnected", "input_locked": False, "can_submit": False, "turns": [], "requests": []})
            return
        if parsed.path.startswith("/api/questions/") and parsed.path.endswith("/evidence"):
            import pymupdf as fitz
            qid = parsed.path.split("/")[3]
            with closing(connect()) as conn, conn:
                question = as_json(conn.execute("SELECT q.*,p.source_path FROM questions q JOIN papers p ON p.id=q.paper_id WHERE q.id=?", (qid,)).fetchone())
            if not question:
                self.send_json({"error": "题目不存在"}, HTTPStatus.NOT_FOUND); return
            regions = json_load(question.get("regions_json"), [])
            try:
                index = int(parse_qs(parsed.query).get("region", ["0"])[0])
                region = regions[index]
                pdf = (ROOT / question["source_path"]).resolve()
                if PAPERS_DIR not in pdf.parents:
                    raise ValueError("invalid file")
                with fitz.open(str(pdf)) as document:
                    pix = document[region["page"] - 1].get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(region["bbox"]), alpha=False)
                    raw = pix.tobytes("png")
                self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
            except (ValueError, IndexError, KeyError):
                self.send_json({"error": "证据区域不存在"}, HTTPStatus.NOT_FOUND)
            return
        if parsed.path.startswith("/api/bank/") and parsed.path.rsplit("/", 1)[-1] in ("question", "analysis", "answer"):
            parts = parsed.path.split("/")
            role = parts[-1]
            library = parse_qs(parsed.query).get('view',['probe'])[0]=='library'
            with closing(connect()) as conn, conn:
                try:
                    if not library:require_access(conn,parts[3],role)
                except ValueError as exc:
                    self.send_json({'error':str(exc)},403);return
                resource = as_json(conn.execute("SELECT * FROM bank_resources WHERE bank_id=?", (parts[3],)).fetchone())
                if resource and resource.get(role + "_path"):
                    path = (DATA / resource[role + "_path"]).resolve()
                    if (DATA / "bank-assets") in path.parents and path.is_file():
                        record_view(conn,parts[3],role)
                        conn.commit()
                        self.send_file(path, "image/png"); return
            self.send_json({"error": "题库资源缺失"}, HTTPStatus.NOT_FOUND); return
        if parsed.path.startswith("/api/papers/") and parsed.path.endswith("/file"):
            paper_id = parsed.path.split("/")[3]
            conn = connect()
            try:
                paper = as_json(conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone())
            finally:
                conn.close()
            if not paper or not paper.get("source_path"):
                self.send_json({"error": "paper file not found"}, HTTPStatus.NOT_FOUND)
                return
            pdf_path = (ROOT / paper["source_path"]).resolve()
            if PAPERS_DIR not in pdf_path.parents or not pdf_path.is_file():
                self.send_json({"error": "paper file not found"}, HTTPStatus.NOT_FOUND)
                return
            self.send_file(pdf_path, "application/pdf")
            return
        conn = connect()
        try:
            if parsed.path == "/api/health":
                self.send_json({"ok": True, "app": "mathlens", "version": VERSION, "data_id": data_identity(DATA)})
            elif parsed.path == "/api/bootstrap":
                self.send_json(bootstrap())
            elif parsed.path == "/api/profile":
                self.send_json(build_profile(conn))
            elif parsed.path == "/api/loop":
                self.send_json(loop_snapshot(conn))
            elif parsed.path == "/api/papers":
                self.send_json({"papers": rows(conn, "SELECT * FROM papers ORDER BY exam_date DESC, created_at DESC")})
            elif parsed.path == "/api/bank":
                query=parse_qs(parsed.query);category=query.get('math_type',[''])[0];year=query.get('year',[''])[0]
                bank=[public_bank(conn,r[0],view='library') for r in conn.execute("SELECT id FROM bank_questions WHERE source!='本地示例题库' ORDER BY id")]
                self.send_json({'bank':[b for b in bank if (not category or str(b['math_type'])==category) and (not year or b['year']==year)]})
            elif parsed.path=='/api/versions':
                self.send_json({'versions':rows(conn,'SELECT * FROM record_versions ORDER BY created_at DESC LIMIT 100'),'reports':rows(conn,'SELECT id,paper_id,created_at FROM agent_reports ORDER BY created_at DESC LIMIT 100')})
            elif parsed.path=='/api/screen':
                path=DATA/'screen.json';self.send_json(json_load(path.read_text(encoding='utf8'),{}) if path.is_file() else {})
            elif parsed.path=='/api/drafts':
                key=parse_qs(parsed.query).get('key',[''])[0];path=DATA/'drafts'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
                self.send_json(json_load(path.read_text(encoding='utf8'),{}) if path.is_file() else {})
            elif parsed.path=='/api/mobile-upload/state':self.send_json(MOBILE.state() if MOBILE else {'active':False,'images':[]})
            elif parsed.path=='/api/maintenance/backups':
                self.send_json({'backups':[{'name':p.name,'bytes':p.stat().st_size} for p in sorted((DATA/'backups').glob('*.zip'),reverse=True)]})
            else:
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        finally:
            conn.close()

    def agent_post(self, parsed):
        if not BRIDGE:
            raise ValueError("会话服务未启动")
        if self.headers.get_content_type() != "application/json":
            raise ValueError("需要 application/json")
        if int(self.headers.get("Content-Length", "0")) > 100000:
            raise ValueError("请求过长")
        body = self.read_json()
        action = parsed.path.removeprefix("/api/agent/")
        if action == "connect":
            result = BRIDGE.connect()
        elif action == "send":
            result = BRIDGE.submit(body.get("text", ""), body.get("request_id"), body.get("context"), body.get('image_ids', []))
        elif action == "respond":
            result = BRIDGE.respond(str(body.get("request_id")), body)
        elif action == "retry":
            result = BRIDGE.retry()
        elif action=='abandon':
            result=BRIDGE.abandon(body.get('confirmed'))
        elif action=='upgrade-tools':result=BRIDGE.upgrade_tools(body.get('confirmed'))
        elif action == "interrupt":
            result = BRIDGE.interrupt()
        else:
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        self.send_json(result)

    def api_post(self, parsed):
        if parsed.path == '/api/answer-images':
            self.upload_answer_images()
            return
        if parsed.path == "/api/papers/import":
            self.import_paper()
            return
        conn = connect()
        try:
            if parsed.path=='/api/mobile-upload/start':
                body=self.read_json()
                if body.get('confirmed') is not True:raise ValueError('请确认仅在可信局域网临时接收照片')
                global MOBILE
                if MOBILE is None:MOBILE=MobileInbox(connect,DATA,mobile_guard)
                self.send_json(MOBILE.start(body.get('target')))
            elif parsed.path=='/api/mobile-upload/stop':self.send_json(MOBILE.stop() if MOBILE else {'active':False})
            elif parsed.path=='/api/drafts':
                body=self.read_json();key=body.get('key');value=body.get('value')
                if not isinstance(key,str) or len(key)>300 or len(json.dumps(value))>120000:raise ValueError('草稿过长或标识不合法')
                folder=DATA/'drafts';folder.mkdir(exist_ok=True);path=folder/(hashlib.sha256(key.encode()).hexdigest()+'.json');temporary=folder/(uuid.uuid4().hex+'.tmp')
                temporary.write_text(json.dumps({'key':key,'value':value},ensure_ascii=False),encoding='utf8');temporary.replace(path);self.send_json({'ok':True})
            elif parsed.path=='/api/maintenance/backup':self.send_json(backup(DATA,ROOT))
            elif parsed.path=='/api/maintenance/cleanup':
                result=cleanup_images(conn,DATA);conn.commit();self.send_json(result)
            elif parsed.path=='/api/maintenance/restore':
                body=self.read_json();name=Path(body.get('name','')).name
                archive=DATA/'backups'/name
                if archive.parent.resolve()!=(DATA/'backups').resolve() or not archive.is_file() or archive.suffix!='.zip':raise ValueError('本地备份不存在')
                self.send_json(restore(archive,DATA.parent/('mathlens-restored-'+uuid.uuid4().hex[:8])))
            elif parsed.path=='/api/screen':
                body=self.read_json()
                if len(json.dumps(body))>6000:raise ValueError('页面上下文过长')
                (DATA/'screen.json').write_text(json.dumps(body,ensure_ascii=False),encoding='utf8');self.send_json({'ok':True})
            elif parsed.path=='/api/preferences':
                value=save_preferences(conn,self.read_json());conn.commit();self.send_json(value)
            elif parsed.path.startswith('/api/bank/') and parsed.path.endswith('/reveal'):
                body=self.read_json();result=reveal(conn,parsed.path.split('/')[3],body.get('role','question'),body.get('confirmed'));conn.commit();self.send_json(result)
            elif parsed.path.startswith('/api/attempts/') and parsed.path.endswith('/supplement'):
                aid=parsed.path.split('/')[3];result=supplement_attempt(conn,aid,self.read_json());conn.commit()
                pid=conn.execute('SELECT probe_id FROM probe_attempts WHERE id=?',(aid,)).fetchone()[0]
                if BRIDGE and BRIDGE.connected:self.request_probe_feedback(conn,pid,aid)
                self.send_json(result)
            elif parsed.path.startswith('/api/attempts/') and parsed.path.endswith('/revise'):
                body=self.read_json();result=revise_assessment(conn,parsed.path.split('/')[3],body.get('assessment',{}),body.get('reason'));conn.commit();self.send_json(result)
            elif parsed.path.startswith('/api/probes/') and parsed.path.endswith('/replace'):
                result=replace_probe(conn,parsed.path.split('/')[3],self.read_json());conn.commit();self.send_json(result)
            elif parsed.path.startswith('/api/reports/') and parsed.path.endswith('/restore'):
                body=self.read_json();row=conn.execute('SELECT * FROM agent_reports WHERE id=?',(parsed.path.split('/')[3],)).fetchone()
                if not row or not body.get('reason'):raise ValueError('报告不存在或缺少恢复原因')
                report=json.loads(row['report_json']);report['revision_reason']=body['reason'];report['restored_at']=now_iso()
                result=apply_report(conn,row['paper_id'],report,ROOT);conn.commit();self.send_json(result)
            elif parsed.path == "/api/papers":
                body = self.read_json()
                paper_id = "paper-" + uuid.uuid4().hex[:10]
                conn.execute("INSERT INTO papers(id,title,exam_date,score,total_score,duration,source_name,import_status,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                             (paper_id, body.get("title") or "未命名试卷", body.get("exam_date"), float(body.get("score") or 0), float(body.get("total_score") or 150), int(body.get("duration") or 0), body.get("source_name"), "needs_review", now_iso()))
                conn.commit()
                self.send_json({"paper": as_json(conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone())}, HTTPStatus.CREATED)
            elif parsed.path.startswith("/api/papers/") and parsed.path.endswith("/analyze"):
                paper_id = parsed.path.split("/")[3]
                result = analyze_paper_record(conn, paper_id)
                if BRIDGE and BRIDGE.connected:
                    BRIDGE.submit("这份已完成试卷已完成初步切分，请读取任务包与原图，分析作答并反馈；已有报告时先核对是否需要增量修订。", str(uuid.uuid4()), {"paper_id": paper_id})
                self.send_json(result, HTTPStatus.CREATED)
            elif parsed.path.startswith("/api/papers/") and parsed.path.endswith("/agent-report"):
                paper_id = parsed.path.split("/")[3]
                result = apply_report(conn, paper_id, self.read_json(), ROOT)
                conn.commit()
                self.send_json(result, HTTPStatus.CREATED)
            elif parsed.path.startswith("/api/probes/") and parsed.path.endswith("/submit"):
                if BRIDGE and not BRIDGE.connected:
                    raise ValueError("请先连接 Codex，以便提交后获得 Agent 反馈")
                body = self.read_json()
                result = submit_probe(conn, parsed.path.split("/")[3], body)
                conn.commit()
                if BRIDGE:
                    try:self.request_probe_feedback(conn, parsed.path.split('/')[3],result['attempt_id'])
                    except (ValueError,RuntimeError) as exc:result['agent_error']=str(exc)
                self.send_json(result, HTTPStatus.CREATED)
            elif parsed.path.startswith('/api/probes/') and parsed.path.endswith('/feedback'):
                body = self.read_json()
                result = self.request_probe_feedback(conn, parsed.path.split('/')[3],body.get('attempt_id'))
                self.send_json(result)
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
                    conn.execute("UPDATE questions SET review_status=? WHERE id=?", ("训练中", body.get("question_id")))
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
                init_access(conn);conn.commit()
                self.send_json({"imported": count}, HTTPStatus.CREATED)
            else:
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            conn.rollback()
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        finally:
            conn.close()

    def request_probe_feedback(self, conn, probe_id, attempt_id):
        if not BRIDGE or not BRIDGE.connected:
            raise ValueError('请先连接 Codex，作答已保留，可连接后重发核对')
        attempt = conn.execute('''SELECT a.images_json,a.response,p.paper_id,p.question_id,p.bank_id FROM probe_attempts a
          JOIN diagnostic_probes p ON a.probe_id=p.id WHERE a.id=? AND p.id=?''',(attempt_id,probe_id)).fetchone()
        if not attempt:
            raise ValueError('作答与检验题不一致')
        probe = {k:attempt[k] for k in ('paper_id','question_id','bank_id')}
        context = {"paper_id":probe['paper_id'],"question_id":probe['question_id'],"screen":{**probe,"probe_id":probe_id,"view":"针对性检验","label":"已提交的真实作答"}}
        version=hashlib.sha256((attempt['response']+attempt['images_json']).encode()).hexdigest()[:12]
        # Repeat after a completed but unassessed reply must start a new evaluation, not reuse that reply.
        revision=conn.execute('SELECT count(*) FROM record_versions WHERE record_id=?',(attempt_id,)).fetchone()[0]
        completed=sum(t['status']=='completed' and t.get('context',{}).get('screen',{}).get('probe_id')==probe_id for t in BRIDGE.snapshot().get('turns',[]))
        return BRIDGE.submit(f"检验作答已保存，attempt_id={attempt_id}。请用 mathlens 工具读取真实回答和作答照片、核对并通过 assess 写回评价，再反馈下一步。看不清时 correct=null 并指出需补拍区域。已有评价时不要重复写入。",str(uuid.uuid5(uuid.NAMESPACE_URL,f'mathlens:attempt:{attempt_id}:{version}:{revision}:{completed}')),context,json.loads(attempt['images_json']))

    def upload_answer_images(self):
        content_type = self.headers.get('Content-Type','')
        length = int(self.headers.get('Content-Length','0'))
        if 'multipart/form-data' not in content_type or not 0 < length <= 33 * 1024 * 1024:
            raise ValueError('请上传最多 4 张照片，每张不超过 8 MB')
        message = BytesParser(policy=email_policy).parsebytes(('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+self.rfile.read(length))
        files = [p.get_payload(decode=True) for p in message.iter_parts() if p.get_param('name',header='content-disposition') == 'files'] if message.is_multipart() else []
        if not 1 <= len(files) <= 4:
            raise ValueError('请上传 1–4 张照片')
        with closing(connect()) as conn, conn:
            images = [save_answer_image(conn, DATA, content or b'') for content in files]
        self.send_json({'images':images}, HTTPStatus.CREATED)

    def import_paper(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_json({"error": "multipart/form-data required"}, HTTPStatus.BAD_REQUEST)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 80 * 1024 * 1024:
            self.send_json({"error": "PDF 上传大小须为 1 字节至 80 MB"}, HTTPStatus.BAD_REQUEST); return
        message = BytesParser(policy=email_policy).parsebytes(("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + self.rfile.read(length))
        fields, filename, content = {}, None, None
        for part in message.iter_parts() if message.is_multipart() else []:
            name = part.get_param("name", header="content-disposition")
            if name == "file":
                filename, content = part.get_filename(), part.get_payload(decode=True)
            elif name:
                fields[name] = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
        if not filename or not content:
            self.send_json({"error": "file required"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            import pymupdf as fitz
            with fitz.open(stream=content, filetype="pdf") as document:
                if document.is_encrypted or not len(document):
                    raise ValueError("试卷无法读取")
        except Exception:
            self.send_json({"error": "请上传可读取、未加密的 PDF"}, HTTPStatus.BAD_REQUEST); return
        digest = hashlib.sha256(content).hexdigest()
        with closing(connect()) as conn, conn:
            previous = as_json(conn.execute("SELECT * FROM papers WHERE source_sha256=? ORDER BY created_at LIMIT 1", (digest,)).fetchone())
        if previous:
            self.send_json({"paper": previous, "sha256": digest, "reused": True}); return
        paper_id = "paper-" + uuid.uuid4().hex[:10]
        filename = Path(filename).name
        target_dir = PAPERS_DIR / paper_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        target.write_bytes(content)
        title = fields.get("title") or Path(filename).stem
        exam_date = fields.get("exam_date") or date.today().isoformat()
        conn = connect()
        relative_source = str(target.relative_to(ROOT))
        conn.execute("INSERT INTO papers(id,title,exam_date,source_name,source_path,source_sha256,import_status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                     (paper_id, title, exam_date, filename, relative_source, digest, "needs_review", now_iso()))
        conn.commit()
        paper = as_json(conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone())
        conn.close()
        result={'paper':paper,'sha256':digest}
        try:
            with closing(connect()) as conn, conn:
                analysis=analyze_paper_record(conn,paper_id)
                result.update(paper=analysis['paper'],created_questions=analysis['created_questions'],warnings=analysis['warnings'])
            if BRIDGE and BRIDGE.connected:BRIDGE.submit('新试卷已自动切分，请用内置学习工具读取本卷和原图，诊断作答并写回完整报告。',str(uuid.uuid5(uuid.NAMESPACE_URL,'mathlens:paper:'+digest)),{'paper_id':paper_id})
        except (ValueError,RuntimeError,ImportError) as exc:result['analysis_warning']=str(exc)
        self.send_json(result,HTTPStatus.CREATED)


def main():
    global BRIDGE
    import argparse
    parser = argparse.ArgumentParser(description="MathLens local-first paper diagnosis server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--auto-port", action="store_true", help="Fall back to a free local port when the preferred port is blocked")
    args = parser.parse_args()
    init_db()
    try:
        server, failures = bind_server(Handler, args.host, args.port, args.auto_port)
    except RuntimeError as exc:
        parser.exit(1, f'MathLens: {exc}\n')
    try:
        BRIDGE = CodexBridge(ROOT, DATA)
        address = publish_address(DATA, server)
        for failure in failures:
            print(f"Port {failure['port']} unavailable (error {failure['code']}); selected another local port.")
        print(f"MathLens running at {address['url']}")
        print(f"Data directory: {DATA}")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        if BRIDGE: BRIDGE.close()
        clear_address(DATA, os.getpid())
        server.server_close()


if __name__ == "__main__":
    main()
