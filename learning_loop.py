"""Evidence-backed local diagnosis, bank resources and probe events.

Agent reports are explicit inputs. This module does not silently invoke a model
or infer a student's cause from the final answer alone.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from answer_images import init_answer_images, image_records
from bank_access import init_access, register_identity, access, require_access, aliases


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dump(value):
    return json.dumps(value, ensure_ascii=False)


def init_loop(conn):
    init_answer_images(conn)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS bank_resources(
      bank_id TEXT PRIMARY KEY REFERENCES bank_questions(id), metadata_json TEXT NOT NULL,
      question_path TEXT NOT NULL, analysis_path TEXT, answer_path TEXT);
    CREATE TABLE IF NOT EXISTS agent_reports(
      id TEXT PRIMARY KEY, paper_id TEXT NOT NULL REFERENCES papers(id), source_sha256 TEXT NOT NULL,
      report_json TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS question_diagnoses(
      question_id TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
      report_id TEXT NOT NULL REFERENCES agent_reports(id), diagnosis_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS diagnostic_probes(
      id TEXT PRIMARY KEY, paper_id TEXT NOT NULL REFERENCES papers(id),
      question_id TEXT NOT NULL REFERENCES questions(id), bank_id TEXT NOT NULL REFERENCES bank_questions(id),
      skill_id TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'awaiting_response',
      created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS probe_attempts(
      id TEXT PRIMARY KEY, probe_id TEXT NOT NULL REFERENCES diagnostic_probes(id), response TEXT NOT NULL,
      answer_exposed INTEGER NOT NULL DEFAULT 0, elapsed_seconds INTEGER,
      assessment_json TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS learning_events(
      id TEXT PRIMARY KEY, paper_id TEXT NOT NULL REFERENCES papers(id), question_id TEXT REFERENCES questions(id),
      probe_id TEXT REFERENCES diagnostic_probes(id), skill_id TEXT NOT NULL, label TEXT NOT NULL,
      kind TEXT NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS bank_exposures(bank_id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
    """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(questions)")}
    if "regions_json" not in cols:
        conn.execute("ALTER TABLE questions ADD COLUMN regions_json TEXT")
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(papers)")}
    if "source_sha256" not in pcols:
        conn.execute("ALTER TABLE papers ADD COLUMN source_sha256 TEXT")
    acols = {r[1] for r in conn.execute("PRAGMA table_info(probe_attempts)")}
    if "images_json" not in acols:
        conn.execute("ALTER TABLE probe_attempts ADD COLUMN images_json TEXT NOT NULL DEFAULT '[]'")
    init_access(conn)
    conn.executescript('''CREATE TABLE IF NOT EXISTS record_versions(
      id TEXT PRIMARY KEY,kind TEXT,record_id TEXT,payload TEXT,reason TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS retired_probes(probe_id TEXT PRIMARY KEY,reason TEXT,created_at TEXT);''')


def import_image_bank(conn, source: Path, data_root: Path, math_types=(1,2,3)):
    """Copy a user's external local bank. No resource is added to Git."""
    groups={1:'数学一',2:'数学二',3:'数学三'}
    result={'imported':0,'missing':[],'by_type':{}}
    for math_type in math_types:
        if math_type not in groups:raise ValueError('题库类别不合法')
        group=source/'kaoyan_math_images'/groups[math_type]
        if not (group/'answers.json').is_file():
            result['missing'].append(groups[math_type]+'/answers.json');continue
        part=_import_group(conn,group,data_root,math_type,groups[math_type])
        result['imported']+=part['imported'];result['missing']+=part['missing'];result['by_type'][str(math_type)]=part['imported']
    conn.execute('DELETE FROM bank_cross_reviews')
    return result


def _import_group(conn,group,data_root,math_type,label):
    records = json.loads((group / "answers.json").read_text(encoding="utf-8"))
    destination = data_root / "bank-assets"
    imported, missing = 0, []
    for key, q in records.items():
        bid = f"math{math_type}-" + q["paper"] + f"-{q['index']:02d}"
        stem = f"{q['paper']} {label} 第{q['index']}题 · {q.get('knowledge_point') or '待提取'}"
        prefix = f"Q{q['index']:02d}_id{q['question_id']}"
        base = group / q["paper"]
        paths = {}
        for role, path in {"question": base / (prefix + ".png"),
                           "analysis": base / "analysis" / (prefix + "_analysis.png"),
                           "answer": base / "answers" / (prefix + "_answer.png")}.items():
            if path.is_file():
                target = destination / bid / (role + ".png")
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.is_file() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(path.read_bytes()).digest():
                    shutil.copy2(path, target)
                paths[role] = str(target.relative_to(data_root))
        if not paths.get("question") or not paths.get("analysis"):
            missing.append(key)
            continue
        conn.execute("""INSERT INTO bank_questions(id,source,source_ref,stem,answer,explanation,tags_json,fingerprint_json,difficulty,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET stem=excluded.stem,tags_json=excluded.tags_json""",
                     (bid, label+"真题图片库", key, stem, q.get("answer"), "参考解析见原图",
                      dump([q.get("knowledge_point") or "待提取"]), dump({"objects": [q.get("knowledge_point")]}), 3, stamp()))
        conn.execute("""INSERT INTO bank_resources VALUES(?,?,?,?,?) ON CONFLICT(bank_id) DO UPDATE SET
          metadata_json=excluded.metadata_json,question_path=excluded.question_path,
          analysis_path=excluded.analysis_path,answer_path=excluded.answer_path""",
                     (bid, dump({**q, 'math_type':math_type, 'question_sha256':hashlib.sha256((data_root/paths['question']).read_bytes()).hexdigest(), "source_url": "https://github.com/lx-ruc/kaoyanshuxue",
                                 "rights": "外部个人资料导入；第三方题目与解析不随应用分发"}),
                      paths["question"], paths.get("analysis"), paths.get("answer")))
        register_identity(conn,bid,math_type,q['paper'],q['index'],data_root/paths['question'])
        imported += 1
    return {"imported": imported, "missing": missing}


def apply_report(conn, paper_id, report, root):
    paper = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if not paper:
        raise ValueError("试卷不存在")
    pdf = (root / paper["source_path"]).resolve()
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if report.get("source_sha256") != digest:
        raise ValueError("报告与试卷 SHA256 不一致，拒绝写入")
    questions = report.get("questions", [])
    numbers = [str(q["number"]) for q in questions]
    if len(set(numbers)) != len(numbers) or not questions:
        raise ValueError("报告题号缺失或重复")
    expected = report.get("expected_count")
    if expected and set(numbers) != {str(i) for i in range(1, expected + 1)}:
        raise ValueError("报告未覆盖本卷全部题号")
    if not report.get("author") or not report.get("method"):
        raise ValueError("报告必须声明作者及识别方式")
    import pymupdf as fitz
    with fitz.open(str(pdf)) as document:
        for q in questions:
            if not q.get("regions"):
                raise ValueError(f"第{q['number']}题没有原卷证据区域")
            for region in q["regions"]:
                page = int(region["page"])
                if not 1 <= page <= len(document):
                    raise ValueError("证据页码超界")
                rect = fitz.Rect(region["bbox"])
                if rect.is_empty or rect.x0 < 0 or rect.y0 < 0 or not document[page-1].rect.contains(rect):
                    raise ValueError("证据区域超界")
    # A content digest makes repeated submission idempotent.
    rid = "agent-" + hashlib.sha256(dump(report).encode()).hexdigest()[:20]
    if conn.execute("SELECT id FROM agent_reports WHERE id=? AND paper_id=?", (rid, paper_id)).fetchone():
        return {"report_id": rid, "reused": True}
    if conn.execute("SELECT id FROM agent_reports WHERE id=?", (rid,)).fetchone():
        rid += "-" + paper_id
    conn.execute("INSERT INTO agent_reports VALUES(?,?,?,?,?)", (rid, paper_id, digest, dump(report), stamp()))
    for item in questions:
        number = str(item["number"])
        q = conn.execute("SELECT id FROM questions WHERE paper_id=? AND number=? ORDER BY created_at LIMIT 1", (paper_id, number)).fetchone()
        qid = q[0] if q else f"{paper_id}-q-{int(number):02d}"
        regions = item["regions"]
        if not q:
            conn.execute("INSERT INTO questions(id,paper_id,number,created_at) VALUES(?,?,?,?)", (qid, paper_id, number, stamp()))
        conn.execute("""UPDATE questions SET subject=?,stem=?,max_score=?,score_earned=?,correctness=?,review_status=?,knowledge=?,
          fingerprint_json=?,page_start=?,page_end=?,bbox_json=?,regions_json=?,notes=? WHERE id=?""",
                     (item.get("subject", "数学一"), item["stem"], item.get("max_score", 0), item.get("score_earned"), item.get("correctness", "unknown"),
                      "待检验" if item.get("hypotheses") else "已阅卷证据", "｜".join(item.get("knowledge", [])),
                      dump(item.get("fingerprint", {})), regions[0]["page"], regions[-1]["page"], dump(regions[0]["bbox"]),
                      dump(regions), item.get("observation", ""), qid))
        conn.execute("INSERT INTO question_diagnoses VALUES(?,?,?) ON CONFLICT(question_id) DO UPDATE SET report_id=excluded.report_id,diagnosis_json=excluded.diagnosis_json",
                     (qid, rid, dump(item)))
        # Replace only extraction-derived events. User probe attempts remain immutable.
        conn.execute("DELETE FROM learning_events WHERE question_id=? AND kind IN ('exam_error','exam_success','hypothesis','incomplete')", (qid,))
        for event in item.get("skill_events", []):
            if event["kind"] not in ("exam_error", "exam_success", "hypothesis", "incomplete"):
                raise ValueError("不支持的画像事件")
            conn.execute("INSERT INTO learning_events VALUES(?,?,?,?,?,?,?,?,?)",
                         ("event-" + uuid.uuid4().hex, paper_id, qid, None, event["skill_id"], event["label"], event["kind"],
                          dump({"evidence": item.get("observation"), "report_id": rid, "independent": False}), stamp()))
    for probe in report.get("probes", []):
        q = conn.execute("SELECT id FROM questions WHERE paper_id=? AND number=?", (paper_id, str(probe["question_number"]))).fetchone()
        if not q or not conn.execute("SELECT bank_id FROM bank_resources WHERE bank_id=?", (probe["bank_id"],)).fetchone():
            raise ValueError("检验题缺少原题或本地题库资源")
        # The Agent may propose a hidden candidate, but explicitly reserved papers are excluded.
        require_access(conn,probe['bank_id'],internal=True)
        pid = f"{paper_id}-{probe['id']}"
        conn.execute("INSERT INTO diagnostic_probes VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                     (pid, paper_id, q[0], probe["bank_id"], probe["skill_id"], dump(probe), "awaiting_response", stamp()))
    conn.execute("UPDATE papers SET import_status='diagnosed',source_sha256=?,analysis_message=?,analyzed_at=? WHERE id=?",
                 (digest, report.get("summary", "初始诊断已就绪，等待针对性检验"), stamp(), paper_id))
    return {"report_id": rid, "questions": len(questions), "probes": len(report.get("probes", []))}


def skill_profile(conn):
    grouped = {}
    for row in conn.execute("SELECT * FROM learning_events ORDER BY created_at"):
        item = grouped.setdefault(row["skill_id"], {"skill_id": row["skill_id"], "label": row["label"], "events": []})
        item["events"].append({**dict(row), "detail": json.loads(row["detail_json"])})
    for skill in grouped.values():
        events = skill["events"]
        skill["failures"] = sum(e["kind"] in ("exam_error", "probe_failure") for e in events)
        skill["successes"] = sum(e["kind"] in ("exam_success", "probe_success") for e in events)
        skill["pending"] = sum(e["kind"] in ("hypothesis", "incomplete") for e in events)
        skill["papers"] = len({e["paper_id"] for e in events})
        skill["independent_probe_successes"] = sum(e["kind"] == "probe_success" and e["detail"].get("independent") for e in events)
        skill["state"] = "待检验"
        if skill["failures"]:
            skill["state"] = "有错误证据，原因待区分"
        elif skill["successes"]:
            skill["state"] = "单卷有成功证据"
        if skill["independent_probe_successes"]:
            skill["state"] = "已有检验成功证据，待新卷复核"
    return sorted(grouped.values(), key=lambda x: (-x["failures"], -x["pending"], x["label"]))


def probe_payload(conn, row):
    item = {**dict(row), **json.loads(row["payload_json"])}
    item["id"] = row["id"]
    state=access(conn,row['bank_id'])
    attempts = [dict(r) for r in conn.execute("SELECT * FROM probe_attempts WHERE probe_id=? ORDER BY created_at", (row["id"],))]
    for attempt in attempts:
        attempt["assessment"] = json.loads(attempt["assessment_json"]) if attempt["assessment_json"] else None
        attempt["image_ids"] = json.loads(attempt.pop("images_json", "[]"))
    item["attempts"] = attempts
    item["bank_exposed"] = bool(conn.execute("SELECT bank_id FROM bank_exposures WHERE bank_id=?", (row["bank_id"],)).fetchone())
    item['access']=state
    if not state['can_view']:
        return {k:item[k] for k in ('id','paper_id','question_id','bank_id','priority','status','access','attempts')}
    item["question_image"] = f"/api/bank/{row['bank_id']}/question"
    if state['analysis_allowed']:item["analysis_image"] = f"/api/bank/{row['bank_id']}/analysis"
    # Reference answers are revealed only after the user has submitted.
    if not attempts or not state['analysis_allowed']:
        for field in ("expected", "accepted", "rubric", "solution_note"):
            item.pop(field, None)
    item.pop("payload_json", None)
    return item


def loop_snapshot(conn):
    reports = []
    seen_papers = set()
    for row in conn.execute("SELECT * FROM agent_reports ORDER BY created_at DESC,rowid DESC"):
        if row["paper_id"] in seen_papers:
            continue
        seen_papers.add(row["paper_id"])
        data = json.loads(row["report_json"])
        reports.append({"id": row["id"], "paper_id": row["paper_id"], "summary": data.get("summary"),
                        "limitations": data.get("limitations", []), "author": data["author"], "method": data["method"],
                        "score_status": data.get("score_status"), "priorities": data.get("priorities", [])})
    diagnoses = {}
    for row in conn.execute("SELECT * FROM question_diagnoses"):
        diagnoses[row["question_id"]] = json.loads(row["diagnosis_json"])
    probes = [probe_payload(conn, row) for row in conn.execute("SELECT * FROM diagnostic_probes WHERE id NOT IN (SELECT probe_id FROM retired_probes) ORDER BY created_at,id")]
    return {"reports": reports, "diagnoses": diagnoses, "probes": probes, "skills": skill_profile(conn)}


def normalize_answer(value):
    return re.sub(r"[\s。$\\{}]", "", value).lower().replace("，", ",").replace("θ", "theta").replace("σ", "sigma").replace("−", "-").replace("（", "(").replace("）", ")")


def submit_probe(conn, probe_id, body):
    row = conn.execute("SELECT * FROM diagnostic_probes WHERE id=?", (probe_id,)).fetchone()
    if not row:
        raise ValueError("检验任务不存在")
    require_access(conn,row['bank_id'])
    if conn.execute('SELECT 1 FROM retired_probes WHERE probe_id=?',(probe_id,)).fetchone():raise ValueError('检验已被替换，请打开新的检验')
    response = str(body.get("response", "")).strip()
    image_ids = [r['id'] for r in image_records(conn, body.get('image_ids', []))]
    if not response and not image_ids:
        raise ValueError("请填写作答、上传照片，或明确写“不知道”")
    if len(response) > 16000:
        raise ValueError("作答过长")
    payload = json.loads(row["payload_json"])
    exposed = bool(body.get("answer_exposed")) or any(conn.execute("SELECT bank_id FROM bank_exposures WHERE bank_id=?", (bid,)).fetchone() for bid in aliases(conn,row['bank_id']))
    elapsed = body.get("elapsed_seconds")
    if elapsed is not None and (not isinstance(elapsed, (int, float)) or not 0 <= elapsed <= 86400):
        raise ValueError("用时不合法")
    accepted = payload.get("accepted", [])
    matched = not image_ids and bool(accepted) and normalize_answer(response) in {normalize_answer(a) for a in accepted}
    # Unrecognised free-text answers are not automatically classified as wrong.
    assessment = {"correct": True, "method": "explicit_answer_match", "feedback": "与该环节的参考回答一致；仅增加一次成功证据。"} if matched else None
    request_id = body.get("request_id")
    if request_id and not re.fullmatch(r"[a-fA-F0-9-]{32,36}", request_id):
        raise ValueError("作答请求标识不合法")
    aid = "attempt-" + (request_id if request_id else uuid.uuid4().hex)
    previous = conn.execute("SELECT * FROM probe_attempts WHERE id=?", (aid,)).fetchone()
    if previous:
        if previous["probe_id"] != probe_id or previous["response"] != response or json.loads(previous["images_json"]) != image_ids:
            raise ValueError("同一请求标识不能用于不同作答")
        return {"attempt_id":aid,"reused":True,"assessment":json.loads(previous["assessment_json"]) if previous["assessment_json"] else None}
    conn.execute("INSERT INTO probe_attempts(id,probe_id,response,answer_exposed,elapsed_seconds,assessment_json,created_at,images_json) VALUES(?,?,?,?,?,?,?,?)",
                 (aid, probe_id, response, int(exposed), int(elapsed) if elapsed is not None else None, dump(assessment) if assessment else None, stamp(),dump(image_ids)))
    conn.execute("UPDATE diagnostic_probes SET status=? WHERE id=?", ("assessed" if matched else "awaiting_assessment", probe_id))
    if matched:
        conn.execute("INSERT INTO learning_events VALUES(?,?,?,?,?,?,?,?,?)",
                     ("event-"+uuid.uuid4().hex, row["paper_id"], row["question_id"], probe_id, row["skill_id"], payload["skill_label"],
                      "probe_success", dump({"attempt_id": aid, "independent": not exposed, "answer_exposed": exposed}), stamp()))
    return {"attempt_id": aid, "status": "assessed" if matched else "awaiting_assessment", "assessment": assessment}


def assess_attempt(conn, attempt_id, assessment):
    row = conn.execute("""SELECT a.*,p.paper_id,p.question_id,p.skill_id,p.payload_json FROM probe_attempts a
      JOIN diagnostic_probes p ON p.id=a.probe_id WHERE a.id=?""", (attempt_id,)).fetchone()
    if not row:
        raise ValueError("作答不存在")
    if row["assessment_json"]:
        raise ValueError("作答已评价；更正需要显式撤销原事件，不能重复累计")
    if 'correct' not in assessment or (assessment['correct'] is not None and type(assessment['correct']) is not bool) or not assessment.get("feedback") or not assessment.get("author"):
        raise ValueError("评价需要明确正误、理由和作者")
    payload = json.loads(row["payload_json"])
    assessment["method"] = "agent_review"
    conn.execute("UPDATE probe_attempts SET assessment_json=? WHERE id=?", (dump(assessment), attempt_id))
    conn.execute("UPDATE diagnostic_probes SET status=? WHERE id=?", ('needs_supplement' if assessment.get('correct') is None else 'assessed',row["probe_id"]))
    if assessment.get('correct') is None:return {'attempt_id':attempt_id,'assessment':assessment,'needs_supplement':True}
    conn.execute("INSERT INTO learning_events VALUES(?,?,?,?,?,?,?,?,?)",
                 ("event-"+uuid.uuid4().hex,row["paper_id"],row["question_id"],row["probe_id"],row["skill_id"],payload["skill_label"],
                  "probe_success" if assessment["correct"] else "probe_failure",
                  dump({"attempt_id":attempt_id,"independent":not bool(row["answer_exposed"]),"author":assessment["author"]}),stamp()))
    return {"attempt_id":attempt_id,"assessment":assessment}


def save_version(conn,kind,record_id,payload,reason):
    if not isinstance(reason,str) or not reason.strip():raise ValueError('更正需要说明原因')
    conn.execute('INSERT INTO record_versions VALUES(?,?,?,?,?,?)',('version-'+uuid.uuid4().hex,kind,record_id,dump(payload),reason,stamp()))


def clear_attempt_assessment(conn,row,reason):
    save_version(conn,'attempt',row['id'],dict(row),reason)
    conn.execute("DELETE FROM learning_events WHERE probe_id=? AND json_extract(detail_json,'$.attempt_id')=?",(row['probe_id'],row['id']))
    conn.execute('UPDATE probe_attempts SET assessment_json=NULL WHERE id=?',(row['id'],))
    conn.execute("UPDATE diagnostic_probes SET status='awaiting_assessment' WHERE id=?",(row['probe_id'],))


def revise_assessment(conn,attempt_id,assessment,reason):
    row=conn.execute('SELECT * FROM probe_attempts WHERE id=?',(attempt_id,)).fetchone()
    if not row:raise ValueError('作答不存在')
    clear_attempt_assessment(conn,row,reason)
    return assess_attempt(conn,attempt_id,assessment)


def supplement_attempt(conn,attempt_id,body):
    row=conn.execute('SELECT * FROM probe_attempts WHERE id=?',(attempt_id,)).fetchone()
    if not row:raise ValueError('作答不存在')
    images=list(dict.fromkeys(json.loads(row['images_json'])+[r['id'] for r in image_records(conn,body.get('image_ids',[]))]))
    if len(images)>4:raise ValueError('同一次作答累计最多 4 张照片，请新建复测')
    addition=str(body.get('response','')).strip()
    if not addition and images==json.loads(row['images_json']):raise ValueError('请补充思路或照片')
    if len(addition)>16000:raise ValueError('补充文字过长')
    clear_attempt_assessment(conn,row,body.get('reason') or '用户补充手写步骤')
    conn.execute('UPDATE probe_attempts SET response=?,images_json=? WHERE id=?',(row['response']+('\n\n补充：'+addition if addition else ''),dump(images),attempt_id))
    return {'attempt_id':attempt_id,'status':'awaiting_assessment'}


def replace_probe(conn,probe_id,body):
    row=conn.execute('SELECT * FROM diagnostic_probes WHERE id=?',(probe_id,)).fetchone()
    if not row:raise ValueError('检验不存在')
    reason=body.get('reason');save_version(conn,'probe',probe_id,dict(row),reason)
    payload=json.loads(row['payload_json']);payload.update(body.get('changes',{}))
    for field in ('bank_id','skill_id','skill_label','prompt','discriminates'):
        if not payload.get(field):raise ValueError('新检验缺少 '+field)
    require_access(conn,payload['bank_id'],internal=True)
    pid=row['paper_id']+'-probe-'+uuid.uuid4().hex[:12]
    conn.execute('INSERT INTO diagnostic_probes VALUES(?,?,?,?,?,?,?,?)',(pid,row['paper_id'],row['question_id'],payload['bank_id'],payload['skill_id'],dump(payload),'awaiting_response',stamp()))
    conn.execute('INSERT OR IGNORE INTO retired_probes VALUES(?,?,?)',(probe_id,reason,stamp()))
    return {'probe_id':pid,'replaces':probe_id}
