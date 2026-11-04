"""Evidence-backed local diagnosis, bank resources and probe events.

Agent reports are explicit inputs. This module does not silently invoke a model
or infer a student's cause from the final answer alone.
"""
from __future__ import annotations

from app.storage.paths import paper_path, relative_file, resolve_file, connection_data
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from app.storage.images import init_answer_images, image_records
from app.bank.access import init_access, register_identity, access, require_access, policy_group
from app.learning.report_contract import report_issues, present_diagnosis, text


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def touch_paper(conn,paper_id):
    conn.execute('UPDATE papers SET updated_at=? WHERE id=?',(stamp(),paper_id))


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
    if 'image_roles_json' not in acols:
        conn.execute("ALTER TABLE probe_attempts ADD COLUMN image_roles_json TEXT NOT NULL DEFAULT '{}'")
    init_access(conn)
    conn.executescript('''CREATE TABLE IF NOT EXISTS record_versions(
      id TEXT PRIMARY KEY,kind TEXT,record_id TEXT,payload TEXT,reason TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS retired_probes(probe_id TEXT PRIMARY KEY,reason TEXT,created_at TEXT);''')
    conn.execute('''CREATE TABLE IF NOT EXISTS attempt_supplements(
      request_id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL REFERENCES probe_attempts(id),
      payload_sha256 TEXT NOT NULL,created_at TEXT NOT NULL)''')


def import_image_bank(conn, source: Path, data_root: Path, math_types=(1,2,3)):
    """Copy a user's external local bank. No resource is added to Git."""
    groups={1:'数学一',2:'数学二',3:'数学三'}
    result={'imported':0,'missing':[],'by_type':{},'preserved_navigation':[]}
    for math_type in math_types:
        if math_type not in groups:raise ValueError('题库类别不合法')
        group=source/'kaoyan_math_images'/groups[math_type]
        if not (group/'answers.json').is_file():
            result['missing'].append(groups[math_type]+'/answers.json');continue
        part=_import_group(conn,group,data_root,math_type,groups[math_type])
        result['imported']+=part['imported'];result['missing']+=part['missing'];result['by_type'][str(math_type)]=part['imported']
        result['preserved_navigation']+=part['preserved_navigation']
    conn.execute('DELETE FROM bank_cross_reviews')
    return result


def _import_group(conn,group,data_root,math_type,label):
    records = json.loads((group / "answers.json").read_text(encoding="utf-8"))
    from app.storage.boundaries import library_root, material_path
    destination = library_root(data_root) / "bank-assets"
    imported, missing, preserved = 0, [], []
    for key, q in records.items():
        bid = f"math{math_type}-" + q["paper"] + f"-{q['index']:02d}"
        stem = f"{q['paper']} {label} 第{q['index']}题 · {q.get('knowledge_point') or '待提取'}"
        prefix = f"Q{q['index']:02d}_id{q['question_id']}"
        base = group / q["paper"]
        sources={"question": base / (prefix + ".png"),
                           "analysis": base / "analysis" / (prefix + "_analysis.png"),
                           "answer": base / "answers" / (prefix + "_answer.png")}
        from app.bank.metadata import preserve_on_import
        if preserve_on_import(conn,data_root,bid,sources,source_answer=q.get('answer')):
            preserved.append(bid)
            imported+=1
            continue
        paths = {}
        for role, path in sources.items():
            if path.is_file():
                target = destination / bid / (role + ".png")
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.is_file() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(path.read_bytes()).digest():
                    shutil.copy2(path, target)
                paths[role] = str(target.relative_to(library_root(data_root)))
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
                     (bid, dump({**q, 'math_type':math_type, 'question_sha256':hashlib.sha256((material_path(data_root,paths['question'])).read_bytes()).hexdigest(), "source_url": "https://github.com/lx-ruc/kaoyanshuxue",
                                 "rights": "外部个人资料导入；第三方题目与解析不随应用分发"}),
                      paths["question"], paths.get("analysis"), paths.get("answer")))
        register_identity(conn,bid,math_type,q['paper'],q['index'],material_path(data_root,paths['question']))
        conn.execute("UPDATE bank_questions SET collection_id='zhenti' WHERE id=?",(bid,))
        imported += 1
    return {"imported": imported, "missing": missing, "preserved_navigation":preserved}


def apply_report(conn, paper_id, report, root, *, question_numbers=None):
    issues=report_issues(report)
    if issues:raise ValueError('报告格式不完整，请按 report_contract 补齐：'+'；'.join(issues[:12])+('；还有其他缺失字段' if len(issues)>12 else ''))
    paper = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if not paper:
        raise ValueError("试卷不存在")
    if paper['archived_at']:raise ValueError('请先恢复已归档试卷')
    pdf = paper_path(connection_data(conn),paper["source_path"],root)
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
                if q.get('evidence_status')=='missing' and q.get('correctness')=='unknown' and report.get('completion') in ('partial','needs_material'):
                    continue
                raise ValueError(f"第{q['number']}题没有原卷证据区域")
            for region in q["regions"]:
                page = int(region["page"])
                if not 1 <= page <= len(document):
                    raise ValueError("证据页码超界")
                rect = fitz.Rect(region["bbox"])
                if rect.is_empty or rect.x0 < 0 or rect.y0 < 0 or not document[page-1].rect.contains(rect):
                    raise ValueError(f"证据区域超界：第{page}页区域{region['bbox']}；须使用PDF点坐标，页面范围{list(document[page-1].rect)}，不是渲染图片像素")
    # A content digest makes repeated submission idempotent.
    rid = "agent-" + hashlib.sha256(dump(report).encode()).hexdigest()[:20]
    if conn.execute("SELECT id FROM agent_reports WHERE id=? AND paper_id=?", (rid, paper_id)).fetchone():
        return {"report_id": rid, "reused": True}
    if conn.execute("SELECT id FROM agent_reports WHERE id=?", (rid,)).fetchone():
        rid += "-" + paper_id
    conn.execute("INSERT INTO agent_reports VALUES(?,?,?,?,?)", (rid, paper_id, digest, dump(report), stamp()))
    for item in questions:
        if question_numbers is not None and item['number'] not in question_numbers:
            continue
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
                      dump(item.get("fingerprint", {})), regions[0]["page"] if regions else None, regions[-1]["page"] if regions else None, dump(regions[0]["bbox"]) if regions else None,
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
    created=stamp()
    conn.execute("UPDATE papers SET import_status=?,source_sha256=?,analysis_message=?,analyzed_at=?,updated_at=? WHERE id=?",
                 ('partial_analysis' if report.get('completion') in ('partial','needs_material') else 'diagnosed',
                  digest, report.get("summary", "初始诊断已就绪，等待针对性检验"), created, created, paper_id))
    return {"report_id": rid, "questions": len(questions), "probes": len(report.get("probes", []))}


def skill_profile(conn):
    from app.learning.legacy_profile import build_profile
    return build_profile(conn)


def probe_payload(conn, row):
    item = {**dict(row), **json.loads(row["payload_json"])}
    item["id"] = row["id"]
    state=access(conn,row['bank_id'])
    attempts = [dict(r) for r in conn.execute("SELECT * FROM probe_attempts WHERE probe_id=? ORDER BY created_at", (row["id"],))]
    for attempt in attempts:
        attempt["assessment"] = json.loads(attempt["assessment_json"]) if attempt["assessment_json"] else None
        if attempt['assessment'] and attempt['assessment'].get('method')=='explicit_answer_match':
            attempt['assessment']=None
            attempt['needs_agent_review']=True
        attempt["image_ids"] = json.loads(attempt.pop("images_json", "[]"))
        attempt['image_roles']=json.loads(attempt.pop('image_roles_json','{}'))
    item["attempts"] = attempts
    if attempts and attempts[-1].get('needs_agent_review'):item['status']='awaiting_assessment'
    item['bank_exposed'] = any(conn.execute('SELECT 1 FROM bank_exposures WHERE bank_id=?',(bid,)).fetchone()
                               for bid in policy_group(conn,row['bank_id']))
    item['access']=state
    if conn.execute("SELECT name FROM sqlite_master WHERE name='probe_goals'").fetchone():
        item['question_ids']=[r[0] for r in conn.execute('''SELECT DISTINCT gq.question_id FROM probe_goals pg
          JOIN goal_questions gq ON gq.goal_id=pg.goal_id WHERE pg.probe_id=?''',(row['id'],))]
    if not state['can_view']:
        return {k:item[k] for k in ('id','paper_id','question_id','question_ids','bank_id','priority','status','access','attempts') if k in item}
    item["question_image"] = f"/api/bank/{row['bank_id']}/question"
    if state['analysis_allowed']:item["analysis_image"] = f"/api/bank/{row['bank_id']}/analysis"
    from app.learning.practice_knowledge import binding_for
    binding=binding_for(conn,row['id'])
    if binding:
        from app.knowledge.catalog import digest
        manifest=binding.get('material_manifest')
        if manifest and digest(manifest)!=binding['snapshot_sha256']:raise ValueError('练习材料版本元数据不一致')
        suffix=f"?probe_id={row['id']}"
        item['question_image']+=suffix
        if state['analysis_allowed']:item['analysis_image']+=suffix
        if manifest:
            question=manifest['resources']['question']
            if question['text']:item['question_text']=question['text']
            if not question['image_file']:
                item.pop('question_image',None);item['question_text']=question['text']
            if state['analysis_allowed']:
                role='analysis' if 'analysis' in manifest['resources'] else 'answer'
                reference=manifest['resources'].get(role)
                if reference and reference['text']:item['analysis_text']=reference['text']
                if reference and reference['image_file']:
                    item['analysis_image']=f"/api/bank/{row['bank_id']}/{role}"+suffix
                elif reference:
                    item.pop('analysis_image',None);item['analysis_text']=reference['text']
    else:
        from app.bank.access import text_resources
        text_resources(conn,row['bank_id'],item,reference=state['analysis_allowed'] and bool(attempts))
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
        issues=report_issues(data)
        reports.append({"id": row["id"], "paper_id": row["paper_id"], "summary": text(data.get("summary")),
                        "limitations": [v for v in data.get('limitations',[]) if isinstance(v,str)] if isinstance(data.get('limitations'),list) else [],
                        "author": text(data.get('author')), "method": text(data.get('method')),
                        "score_status": text(data.get('score_status')), "priorities": [v for v in data.get('priorities',[]) if isinstance(v,dict)] if isinstance(data.get('priorities'),list) else [],
                        'needs_completion':bool(issues),'validation_issues':issues,
                        'review':data.get('review'),'needs_verification':data.get('review',{}).get('status')!='verified' or data.get('completion')!='complete'})
    diagnoses = {}
    for row in conn.execute("SELECT * FROM question_diagnoses"):
        diagnoses[row["question_id"]] = present_diagnosis(json.loads(row["diagnosis_json"]))
    probes = [probe_payload(conn, row) for row in conn.execute("SELECT * FROM diagnostic_probes WHERE id NOT IN (SELECT probe_id FROM retired_probes) ORDER BY created_at,id")]
    result={"reports": reports, "diagnoses": diagnoses, "probes": probes, "skills": skill_profile(conn)}
    from app.knowledge.index import snapshot
    knowledge=snapshot(conn)
    result.update(knowledge=knowledge['nodes'],knowledge_index={k:v for k,v in knowledge.items() if k!='nodes'})
    if conn.execute("SELECT name FROM sqlite_master WHERE name='learning_tasks'").fetchone():
        from app.learning.tasks import task_listing
        from app.learning.plans import practice_state, plan_goals
        result['tasks']=task_listing(conn)
        result['practice_states']=[]
        result['goals']=[]
        has_related=bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='goal_related_probes'").fetchone())
        for current in reports:
            state=practice_state(conn,current['paper_id'])
            plan=conn.execute('SELECT payload_json FROM learning_results WHERE id=?',(state['result_id'],)).fetchone()
            result['practice_states'].append({**state,'limitations':
                json.loads(plan['payload_json'])['result'].get('limitations',[]) if plan else []})
            goal_rows=plan_goals(conn,state)
            result['goals'].extend({**g,'goal':json.loads(g['payload_json']),
                'related_probe_ids':[r[0] for r in conn.execute(
                    'SELECT probe_id FROM goal_related_probes WHERE goal_id=?',(g['id'],))] if has_related else []}
                for g in goal_rows)
            goal_ids={g['id'] for g in goal_rows}
            deferred={item['probe_id']:item['reason'] for item in state.get('deferred_probes',[])}
            for probe in probes:
                if probe['paper_id']!=current['paper_id']:continue
                probe['is_current']=state['is_current'] and probe['id'] in state['probe_ids']
                if probe['id'] in deferred:
                    probe['review_reason']=deferred[probe['id']]
                    for key in ('question_image','question_text','analysis_image','analysis_text','prompt','expected','solution_note','accepted','rubric','payload_json'):
                        probe.pop(key,None)
                probe['linked_goal_ids']=[r[0] for r in conn.execute(
                    'SELECT goal_id FROM probe_goals WHERE probe_id=?',(probe['id'],)) if r[0] in goal_ids]
                if state['explicit_membership']:
                    probe['question_ids']=[r[0] for r in conn.execute('''SELECT DISTINCT gq.question_id
                      FROM probe_goals pg JOIN practice_goals g ON g.id=pg.goal_id
                      JOIN goal_questions gq ON gq.goal_id=g.id WHERE pg.probe_id=? AND g.result_id=?''',
                      (probe['id'],state['result_id']))]
        seen=set();summaries=[]
        for row in conn.execute("SELECT * FROM learning_results WHERE kind='summarize_paper' ORDER BY created_at DESC,rowid DESC"):
            if row['paper_id'] in seen:continue
            seen.add(row['paper_id']);summaries.append({'id':row['id'],'paper_id':row['paper_id'],
                'created_at':row['created_at'],'summary':json.loads(row['payload_json'])['result']})
        result['summaries']=summaries
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_jobs'").fetchone():
        result['question_reviews'] = [{**json.loads(r['review_json']), 'status': r['status'],
                                       'created_at': r['created_at'], 'error': r['error']}
                                      for r in conn.execute('''SELECT review_json,status,created_at,error
                                        FROM workflow_jobs WHERE review_json IS NOT NULL ORDER BY created_at DESC,rowid DESC''')]
    return result


def normalize_answer(value):
    return re.sub(r"[\s。$\\{}]", "", value).lower().replace("，", ",").replace("θ", "theta").replace("σ", "sigma").replace("−", "-").replace("（", "(").replace("）", ")")


def image_roles(ids,value=None):
    value={} if value is None else value
    if not isinstance(value,dict) or set(value)-set(ids) or any(role not in ('own_work','external_solution','marking') for role in value.values()):
        raise ValueError('图片角色不合法；请选择自己的作答、外部解析或事后批改')
    return {iid:value.get(iid,'own_work') for iid in ids}


def has_own_work(attempt):
    if str(attempt.get('response','')).strip():return True
    roles=json.loads(attempt.get('image_roles_json') or '{}')
    return any(roles.get(iid,'own_work')=='own_work' for iid in json.loads(attempt.get('images_json') or '[]'))


def submit_probe(conn, probe_id, body):
    row = conn.execute("SELECT * FROM diagnostic_probes WHERE id=?", (probe_id,)).fetchone()
    if not row:
        raise ValueError("检验任务不存在")
    require_active_probe(conn,probe_id)
    # A new structured analysis invalidates the previous exercise arrangement.
    # Enforce the same boundary for HTTP/CLI writes as for hidden UI cards.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='learning_results'").fetchone() and conn.execute(
        "SELECT 1 FROM learning_results WHERE paper_id=? AND kind='analyze_paper'",(row['paper_id'],)).fetchone():
        from app.learning.plans import practice_state
        state=practice_state(conn,row['paper_id'])
        if not state['is_current'] or probe_id not in state['probe_ids']:
            raise ValueError('本卷分析已更新，请先点击筛选题目，再提交本轮练习；已有作答保留')
    require_access(conn,row['bank_id'])
    if conn.execute('SELECT 1 FROM retired_probes WHERE probe_id=?',(probe_id,)).fetchone():raise ValueError('检验已被替换，请打开新的检验')
    response = str(body.get("response", "")).strip()
    image_ids = [r['id'] for r in image_records(conn, body.get('image_ids', []))]
    roles=image_roles(image_ids,body.get('image_roles'))
    if not response and not image_ids:
        raise ValueError("请填写作答、上传照片，或明确写“不知道”")
    if len(response) > 16000:
        raise ValueError("作答过长")
    payload = json.loads(row["payload_json"])
    exposed = bool(body.get("answer_exposed")) or any(role!='own_work' for role in roles.values()) or any(conn.execute("SELECT bank_id FROM bank_exposures WHERE bank_id=?", (bid,)).fetchone() for bid in policy_group(conn,row['bank_id']))
    elapsed = body.get("elapsed_seconds")
    if elapsed is not None and (not isinstance(elapsed, (int, float)) or not 0 <= elapsed <= 86400):
        raise ValueError("用时不合法")
    # Matching the final value cannot establish that the reasoning is valid.
    # Saving a response never grades it or adds a learning success event.
    assessment = None
    request_id = body.get("request_id")
    if request_id and not re.fullmatch(r"[a-fA-F0-9-]{32,36}", request_id):
        raise ValueError("作答请求标识不合法")
    aid = "attempt-" + (request_id if request_id else uuid.uuid4().hex)
    previous = conn.execute("SELECT * FROM probe_attempts WHERE id=?", (aid,)).fetchone()
    if previous:
        if previous["probe_id"] != probe_id or previous["response"] != response or json.loads(previous["images_json"]) != image_ids or image_roles(image_ids,json.loads(previous['image_roles_json']))!=roles:
            raise ValueError("同一请求标识不能用于不同作答")
        return {"attempt_id":aid,"reused":True,"assessment":json.loads(previous["assessment_json"]) if previous["assessment_json"] else None}
    conn.execute("INSERT INTO probe_attempts(id,probe_id,response,answer_exposed,elapsed_seconds,assessment_json,created_at,images_json) VALUES(?,?,?,?,?,?,?,?)",
                 (aid, probe_id, response, int(exposed), int(elapsed) if elapsed is not None else None, dump(assessment) if assessment else None, stamp(),dump(image_ids)))
    conn.execute('UPDATE probe_attempts SET image_roles_json=? WHERE id=?',(dump(roles),aid))
    conn.execute("UPDATE diagnostic_probes SET status='awaiting_assessment' WHERE id=?", (probe_id,))
    touch_paper(conn,row['paper_id'])
    return {"attempt_id": aid, "status": "awaiting_assessment", "assessment": assessment}


def assess_attempt(conn, attempt_id, assessment):
    from app.learning.student_text import validate_student_text
    validate_student_text({k:v for k,v in assessment.items() if k not in ('author','method','topic_ids')})
    row = conn.execute("""SELECT a.*,p.paper_id,p.question_id,p.skill_id,p.payload_json FROM probe_attempts a
      JOIN diagnostic_probes p ON p.id=a.probe_id WHERE a.id=?""", (attempt_id,)).fetchone()
    if not row:
        raise ValueError("作答不存在")
    require_active_probe(conn,row['probe_id'])
    if row["assessment_json"]:
        raise ValueError("作答已评价；更正需要显式撤销原事件，不能重复累计")
    if 'correct' not in assessment or (assessment['correct'] is not None and type(assessment['correct']) is not bool) or not assessment.get("feedback") or not assessment.get("author"):
        raise ValueError("评价需要明确正误、理由和作者")
    if not has_own_work(dict(row)) and assessment['correct'] is not None:
        raise ValueError('只有外部解析或批改图，不能当作学生作答评分；请保留未知并指出需要自己的解答')
    payload = json.loads(row["payload_json"])
    assessment["method"] = "agent_review"
    conn.execute("UPDATE probe_attempts SET assessment_json=? WHERE id=?", (dump(assessment), attempt_id))
    conn.execute("UPDATE diagnostic_probes SET status=? WHERE id=?", ('needs_supplement' if assessment.get('correct') is None else 'assessed',row["probe_id"]))
    touch_paper(conn,row['paper_id'])
    if assessment.get('correct') is None:return {'attempt_id':attempt_id,'assessment':assessment,'needs_supplement':True}
    conn.execute("INSERT INTO learning_events VALUES(?,?,?,?,?,?,?,?,?)",
                 ("event-"+uuid.uuid4().hex,row["paper_id"],row["question_id"],row["probe_id"],row["skill_id"],payload["skill_label"],
                  "probe_success" if assessment["correct"] else "probe_failure",
                  dump({"attempt_id":attempt_id,"independent":not bool(row["answer_exposed"]),"author":assessment["author"]}),stamp()))
    return {"attempt_id":attempt_id,"assessment":assessment}


def save_version(conn,kind,record_id,payload,reason):
    if not isinstance(reason,str) or not reason.strip():raise ValueError('更正需要说明原因')
    conn.execute('INSERT INTO record_versions VALUES(?,?,?,?,?,?)',('version-'+uuid.uuid4().hex,kind,record_id,dump(payload),reason,stamp()))


def require_active_probe(conn,probe_id):
    row=conn.execute('SELECT p.archived_at,p.id FROM diagnostic_probes d JOIN papers p ON p.id=d.paper_id WHERE d.id=?',(probe_id,)).fetchone()
    if not row:raise ValueError('检验任务不存在')
    if row[0]:raise ValueError('请先恢复已归档试卷')
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='practice_deferred_probes'").fetchone():
        from app.learning.plans import practice_state
        if any(item['probe_id']==probe_id for item in practice_state(conn,row[1]).get('deferred_probes',[])):
            raise ValueError('历史练习原题版本待核，暂不能提交或批改；原作答与反馈保留')


def clear_attempt_assessment(conn,row,reason):
    require_active_probe(conn,row['probe_id'])
    save_version(conn,'attempt',row['id'],dict(row),reason)
    conn.execute("DELETE FROM learning_events WHERE probe_id=? AND json_extract(detail_json,'$.attempt_id')=?",(row['probe_id'],row['id']))
    conn.execute('UPDATE probe_attempts SET assessment_json=NULL WHERE id=?',(row['id'],))
    conn.execute("UPDATE diagnostic_probes SET status='awaiting_assessment' WHERE id=?",(row['probe_id'],))
    paper=conn.execute('SELECT paper_id FROM diagnostic_probes WHERE id=?',(row['probe_id'],)).fetchone()
    touch_paper(conn,paper[0])


def revise_assessment(conn,attempt_id,assessment,reason):
    row=conn.execute('SELECT * FROM probe_attempts WHERE id=?',(attempt_id,)).fetchone()
    if not row:raise ValueError('作答不存在')
    clear_attempt_assessment(conn,row,reason)
    return assess_attempt(conn,attempt_id,assessment)


def supplement_attempt(conn,attempt_id,body):
    row=conn.execute('SELECT * FROM probe_attempts WHERE id=?',(attempt_id,)).fetchone()
    if not row:raise ValueError('作答不存在')
    request_id=body.get('request_id')
    if request_id:
        try:request_id=str(uuid.UUID(request_id))
        except (ValueError,TypeError,AttributeError):raise ValueError('补充请求标识不合法') from None
        sha=hashlib.sha256(json.dumps({k:body.get(k) for k in ('response','image_ids','image_roles','answer_exposed','reason')},
                                    ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
        previous=conn.execute('SELECT * FROM attempt_supplements WHERE request_id=?',(request_id,)).fetchone()
        if previous:
            if previous['attempt_id']!=attempt_id or previous['payload_sha256']!=sha:
                raise ValueError('同一请求不能用于不同补充内容')
            return {'attempt_id':attempt_id,'reused':True,'status':'awaiting_assessment'}
    images=list(dict.fromkeys(json.loads(row['images_json'])+[r['id'] for r in image_records(conn,body.get('image_ids',[]))]))
    roles={**image_roles(json.loads(row['images_json']),json.loads(row['image_roles_json'])),
           **image_roles(body.get('image_ids',[]),body.get('image_roles'))}
    if len(images)>4:raise ValueError('同一次作答累计最多 4 张照片，请新建复测')
    addition=str(body.get('response','')).strip()
    if not addition and images==json.loads(row['images_json']):raise ValueError('请补充思路或照片')
    if len(addition)>16000:raise ValueError('补充文字过长')
    clear_attempt_assessment(conn,row,body.get('reason') or '用户补充手写步骤')
    bank=conn.execute('SELECT bank_id FROM diagnostic_probes WHERE id=?',(row['probe_id'],)).fetchone()[0]
    exposed=bool(row['answer_exposed']) or bool(body.get('answer_exposed')) or any(role!='own_work' for role in roles.values()) or any(
        conn.execute('SELECT 1 FROM bank_exposures WHERE bank_id=?',(bid,)).fetchone() for bid in policy_group(conn,bank))
    conn.execute('UPDATE probe_attempts SET response=?,images_json=?,answer_exposed=?,image_roles_json=? WHERE id=?',
        (row['response']+('\n\n补充：'+addition if addition else ''),dump(images),int(exposed),dump(roles),attempt_id))
    if request_id:
        conn.execute('INSERT INTO attempt_supplements VALUES(?,?,?,?)',(request_id,attempt_id,sha,stamp()))
    return {'attempt_id':attempt_id,'status':'awaiting_assessment'}


def replace_probe(conn,probe_id,body):
    row=conn.execute('SELECT * FROM diagnostic_probes WHERE id=?',(probe_id,)).fetchone()
    if not row:raise ValueError('检验不存在')
    require_active_probe(conn,probe_id)
    reason=body.get('reason');save_version(conn,'probe',probe_id,dict(row),reason)
    payload=json.loads(row['payload_json']);payload.update(body.get('changes',{}))
    for field in ('bank_id','skill_id','skill_label','prompt','discriminates'):
        if not payload.get(field):raise ValueError('新检验缺少 '+field)
    require_access(conn,payload['bank_id'],internal=True)
    pid=row['paper_id']+'-probe-'+uuid.uuid4().hex[:12]
    conn.execute('INSERT INTO diagnostic_probes VALUES(?,?,?,?,?,?,?,?)',(pid,row['paper_id'],row['question_id'],payload['bank_id'],payload['skill_id'],dump(payload),'awaiting_response',stamp()))
    conn.execute('INSERT OR IGNORE INTO retired_probes VALUES(?,?,?)',(probe_id,reason,stamp()))
    touch_paper(conn,row['paper_id'])
    return {'probe_id':pid,'replaces':probe_id}
