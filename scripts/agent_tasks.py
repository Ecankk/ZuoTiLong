"""Local Agent handoff: prepare PDF evidence, apply reports, review probe attempts."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server
from learning_loop import apply_report, assess_attempt, import_image_bank, loop_snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("prepare");p.add_argument("pdf",type=Path);p.add_argument("--bank",type=Path)
    p=sub.add_parser("apply");p.add_argument("paper_id");p.add_argument("report",type=Path)
    p=sub.add_parser("assess");p.add_argument("attempt_id");p.add_argument("assessment",type=Path)
    p=sub.add_parser("import-bank");p.add_argument("directory",type=Path)
    sub.add_parser("pending")
    args=parser.parse_args();server.init_db()
    conn=server.connect()
    try:
        if args.command=="prepare":
            source=args.pdf.resolve();digest=hashlib.sha256(source.read_bytes()).hexdigest()
            old=None
            for row in conn.execute("SELECT * FROM papers WHERE source_path IS NOT NULL ORDER BY created_at"):
                path=(ROOT/row["source_path"]).resolve()
                if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==digest:
                    old=row;break
            if old:
                pid=old["id"]
            else:
                pid="paper-"+digest[:14];target=server.PAPERS_DIR/pid/source.name
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
                conn.execute("INSERT INTO papers(id,title,source_name,source_path,source_sha256,import_status,created_at) VALUES(?,?,?,?,?,?,?)",
                             (pid,source.stem,source.name,str(target.relative_to(ROOT)),digest,"needs_review",server.now_iso()))
            if args.bank:
                print(json.dumps(import_image_bank(conn,args.bank,server.DATA),ensure_ascii=False))
            conn.commit();result=server.analyze_paper_record(conn,pid)
            print(json.dumps({"paper_id":pid,"questions":result["created_questions"],"warnings":result["warnings"],"task":result.get("agent_task")},ensure_ascii=False))
        elif args.command=="import-bank":
            print(json.dumps(import_image_bank(conn,args.directory,server.DATA),ensure_ascii=False));conn.commit()
        elif args.command=="apply":
            report=json.loads(args.report.read_text(encoding="utf-8"))
            applied=apply_report(conn,args.paper_id,report,ROOT);conn.commit()
            task_file=server.DATA/'tasks'/args.paper_id/'request.json'
            if task_file.is_file():
                task=json.loads(task_file.read_text(encoding='utf-8'));task.update(status='report_available',report_id=applied['report_id'])
                task_file.write_text(json.dumps(task,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(applied,ensure_ascii=False))
        elif args.command=="assess":
            print(json.dumps(assess_attempt(conn,args.attempt_id,json.loads(args.assessment.read_text(encoding="utf-8"))),ensure_ascii=False));conn.commit()
        else:
            snapshot=loop_snapshot(conn)
            tasks=[str(p) for p in (server.DATA/"tasks").glob("*/request.json") if not conn.execute('SELECT id FROM agent_reports WHERE paper_id=?',(p.parent.name,)).fetchone()]
            attempts=[{"probe_id":p["id"],"prompt":p["prompt"],"attempts":p["attempts"]} for p in snapshot["probes"] if p["status"]=="awaiting_assessment"]
            print(json.dumps({"tasks":tasks,"awaiting_assessment":attempts},ensure_ascii=False,indent=2))
    except Exception:
        conn.rollback();raise
    finally:
        conn.close()


if __name__=="__main__": main()
