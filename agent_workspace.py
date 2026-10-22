"""Read-only context and bank browsing for a human-directed local Agent.

Topics are navigation aids. Nothing here ranks candidates or decides which
question a student should answer. The Agent must inspect the source images.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from learning_loop import loop_snapshot


def bank_catalog(conn, data_root: Path, *, topics=(), bank_id=None, offset=0, limit=30):
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("offset 必须非负，limit 必须在 1 到 100 之间")
    entries = []
    for row in conn.execute("""SELECT b.id,b.stem,b.fingerprint_json,r.*
      FROM bank_questions b JOIN bank_resources r ON r.bank_id=b.id ORDER BY b.id"""):
        metadata = json.loads(row["metadata_json"])
        topic = metadata.get("knowledge_point") or "待分类"
        if bank_id and row["id"] != bank_id:
            continue
        if topics and not any(t.casefold() in topic.casefold() for t in topics):
            continue
        resources = {}
        for role in ("question", "analysis", "answer"):
            relative = row[f"{role}_path"]
            if not relative:
                resources[role] = None
                continue
            path = (data_root / relative).resolve()
            if not path.is_relative_to(data_root.resolve()):
                raise ValueError("题库资源路径超出个人数据目录")
            resources[role] = {"path": str(path), "exists": path.is_file()}
        note = (data_root / "memory" / "bank" / (row["id"] + ".json")).resolve()
        reading_note = str(note) if note.is_relative_to(data_root.resolve()) and note.is_file() else None
        entries.append({"id": row["id"], "year": metadata.get("paper"),
                        "number": metadata.get("index"), "source_topic": topic,
                        "source_url": metadata.get("source_url"), "resources": resources,
                        "fingerprint": json.loads(row["fingerprint_json"] or "{}"),
                        "reading_note_path": reading_note,
                        "review_status": "not_established_by_catalog"})
    return {"total": len(entries), "offset": offset, "limit": limit,
            "next_offset": offset + limit if offset + limit < len(entries) else None,
            "selection": "Agent 阅读原图后选择；分类筛选为可选目录导航，无排序评分。",
            "items": entries[offset:offset + limit]}


def topic_audit(conn):
    counts = Counter()
    examples = {}
    rich = 0
    total = 0
    missing = 0
    for row in conn.execute("""SELECT b.id,b.fingerprint_json,r.metadata_json
      FROM bank_questions b JOIN bank_resources r ON r.bank_id=b.id ORDER BY b.id"""):
        metadata = json.loads(row["metadata_json"])
        topic = metadata.get("knowledge_point")
        total += 1
        missing += not bool(topic)
        topic = topic or "待分类"
        counts[topic] += 1
        examples.setdefault(topic, []).append(row["id"])
        fp = json.loads(row["fingerprint_json"] or "{}")
        rich += bool(fp.get("micro_skills") or fp.get("operations"))
    return {"scope": "当前已导入图片题库的分类元数据；不代表数学答案正确率或标签逐题准确率",
            "question_count": total, "source_topic_count": len(counts),
            "missing_topic_count": missing, "questions_with_operation_or_micro_skill_fields": rich,
            "classification_model": "每条源记录一个 knowledge_point 字符串",
            "topics": [{"label": t, "count": n, "examples": examples[t][:3]}
                       for t, n in counts.most_common()]}


def workspace_context(conn, data_root: Path, paper_id=None):
    snapshot = loop_snapshot(conn)
    papers = [dict(r) for r in conn.execute("SELECT id,title,import_status FROM papers WHERE source_sha256 IS NOT NULL ORDER BY created_at DESC")]
    if paper_id:
        papers = [p for p in papers if p["id"] == paper_id]
        if not papers:
            raise ValueError("没有找到已导入的试卷")
    ids = {p["id"] for p in papers}
    questions = [dict(r) for r in conn.execute("SELECT id,paper_id,number,regions_json FROM questions ORDER BY paper_id,CAST(number AS INTEGER)") if r["paper_id"] in ids]
    qids = {q["id"] for q in questions}
    memory = data_root / "memory"
    return {
        "purpose": "恢复本地事实和待办，不依赖模型自动记住历史；网页会话状态另由 /api/agent/state 提供。",
        "papers": papers,
        "task_files": [str(p.resolve()) for p in (data_root / "tasks").glob("*/request.json") if p.parent.name in ids],
        "reports": [r for r in snapshot["reports"] if r["paper_id"] in ids],
        "diagnoses": {k: v for k, v in snapshot["diagnoses"].items() if k in qids},
        "probes": [p for p in snapshot["probes"] if p["paper_id"] in ids],
        "profile_scope": "个人全部试卷的证据汇总；即使指定单卷，也保留跨卷背景",
        "profile": snapshot["skills"],
        "memory_files": [str(p.resolve()) for p in sorted(memory.rglob("*.md"))] if memory.exists() else [],
        "bank_reading_note_files": [str(p.resolve()) for p in sorted((memory / "bank").glob("*.json"))] if memory.exists() else [],
        "bank_summary": topic_audit(conn),
    }
