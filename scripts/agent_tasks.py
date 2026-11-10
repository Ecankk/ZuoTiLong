"""Local Agent handoff: prepare PDF evidence, apply reports, review probe attempts."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.storage.paths import paper_path, relative_file
from app.config import AppConfig
from app.storage.database import Database
from app.services.papers import PaperService
from app.common import now_iso
config=AppConfig.from_env(ROOT)
database=Database(config)
from app.learning.loop import import_image_bank, loop_snapshot
from app.agent.workspace import bank_catalog, workspace_context


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("prepare");p.add_argument("pdf",type=Path);p.add_argument("--bank",type=Path)
    p=sub.add_parser("apply");p.add_argument("paper_id");p.add_argument("report",type=Path)
    p=sub.add_parser("assess");p.add_argument("attempt_id");p.add_argument("assessment",type=Path)
    p=sub.add_parser("deliver",help="按当前任务执行身份提交固定契约结果")
    p.add_argument("result",type=Path);p.add_argument("--ticket",type=Path,required=True)
    p=sub.add_parser("import-bank");p.add_argument("directory",type=Path)
    p=sub.add_parser('import-source',help='校验并预演标准题源；仅 --confirm 摘要匹配后写通用库')
    p.add_argument('--source',required=True);p.add_argument('--input',type=Path,required=True)
    p.add_argument('--collection',required=True,help='目标题集ID；已有题目不可改变归属')
    p.add_argument('--overrides',type=Path);p.add_argument('--errata',type=Path);p.add_argument('--asset-root',type=Path)
    p.add_argument('--figures',type=Path);p.add_argument('--figure-root',type=Path)
    choice=p.add_mutually_exclusive_group();choice.add_argument('--dry-run',action='store_true');choice.add_argument('--confirm')
    p.add_argument('--report',type=Path,help='另存不含正文的 JSON 报告')
    p=sub.add_parser('apply-errata');p.add_argument('--input',type=Path,required=True);p.add_argument('--collection',required=True)
    choice=p.add_mutually_exclusive_group();choice.add_argument('--dry-run',action='store_true');choice.add_argument('--confirm')
    p.add_argument('--report',type=Path)
    p=sub.add_parser('export-collection');p.add_argument('--collection',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('import-collection');p.add_argument('--input',type=Path,required=True)
    choice=p.add_mutually_exclusive_group();choice.add_argument('--dry-run',action='store_true');choice.add_argument('--confirm')
    p.add_argument('--report',type=Path)
    sub.add_parser("pending")
    p=sub.add_parser("catalog",help="浏览题库目录和原图路径，由 Agent 自行阅读选择")
    p.add_argument("--topic",action="append",default=[],help="可重复，任一分类包含关键词即可；不是匹配规则")
    p.add_argument("--id",dest="bank_id")
    p.add_argument('--math-type',type=int,choices=(1,2,3),action='append',default=[])
    p.add_argument('--year',action='append',default=[]);p.add_argument('--exclude-year',action='append',default=[])
    p.add_argument("--offset",type=int,default=0);p.add_argument("--limit",type=int,default=30)
    p=sub.add_parser("context",help="恢复个人历史、最新诊断、真实作答和记忆文件入口")
    p.add_argument("--paper",dest="paper_id")
    args=parser.parse_args()
    if args.command=="deliver":
        from app.learning.tasks import deliver
        ticket=json.loads(args.ticket.read_text(encoding='utf8'))
        payload=json.loads(args.result.read_text(encoding='utf8'))
        with database.session(write=True,library_write=payload['kind'] in ('maintain_catalog','annotate_questions')) as task_conn:
            task_conn.row_factory=sqlite3.Row;task_conn.execute('PRAGMA foreign_keys=ON')
            result=deliver(task_conn,ROOT,config.data,payload,ticket)
        print(json.dumps(result,ensure_ascii=False));return
    if args.command=='apply-errata':
        from app.bank.errata import apply_existing
        value=apply_existing(config,args.input,args.collection,args.confirm);text=json.dumps(value,ensure_ascii=False,indent=2)
        if args.report:args.report.write_text(text,encoding='utf8')
        print(text);return
    if args.command=='export-collection':
        from app.bank.collection_packs import export_collection
        print(json.dumps(export_collection(config,args.collection,args.output),ensure_ascii=False));return
    if args.command=='import-collection':
        from app.bank.collection_packs import import_collection
        value=import_collection(config,args.input,args.confirm);text=json.dumps(value,ensure_ascii=False,indent=2)
        if args.report:args.report.write_text(text,encoding='utf8')
        print(text);return
    if args.command in ('prepare','import-bank','import-source','apply','assess'):
        session=config.data/'agent-session.db'
        if session.is_file():
            with sqlite3.connect(session.as_uri()+'?mode=ro',uri=True) as guard_conn:
                row=guard_conn.execute('SELECT payload FROM session WHERE id=1').fetchone()
            state=json.loads(row[0]) if row else {}
            if state.get('active_request') or state.get('external_control') or state.get('status')=='connecting':
                raise ValueError('学习任务/外部会话正在使用资料；旧CLI不能额外写入。当前任务交付请使用deliver及原任务write_ticket。')
        if args.command in ('apply','assess'):
            raise ValueError('旧CLI直接报告写入已停用；请由网页发起任务，再用deliver和context.learning_task.write_ticket交付。')
    if args.command=='import-source':
        from app.bank.source_import import import_source
        result=import_source(config,args.source,args.input,collection=args.collection,asset_root=args.asset_root,
                             overrides=args.overrides,errata=args.errata,confirm=args.confirm,figures=args.figures,figure_root=args.figure_root)
        output=json.dumps(result,ensure_ascii=False,indent=2)
        if args.report:args.report.write_text(output,encoding='utf8')
        print(output);return
    if args.command in ("catalog", "context"):
        conn=database.connect(readonly=True)
        conn.row_factory=sqlite3.Row
    else:
        database.initialize()
        conn=database.connect(library_write=args.command in ('import-bank','prepare'))
    try:
        if args.command in ('prepare','import-bank'):
            # Reserve both stores before a legacy importer can replace assets.
            # Library maintenance holds the same SQLite write reservation.
            conn.execute('BEGIN IMMEDIATE')
        if args.command=="prepare":
            source=args.pdf.resolve();digest=hashlib.sha256(source.read_bytes()).hexdigest()
            old=None
            for row in conn.execute("SELECT * FROM papers WHERE source_path IS NOT NULL ORDER BY created_at"):
                path=paper_path(config.data,row["source_path"],ROOT)
                if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==digest:
                    old=row;break
            if old:
                pid=old["id"]
            else:
                pid="paper-"+digest[:14];target=config.papers/pid/source.name
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
                conn.execute("INSERT INTO papers(id,title,source_name,source_path,source_sha256,import_status,created_at) VALUES(?,?,?,?,?,?,?)",
                             (pid,source.stem,source.name,relative_file(config.data,target),digest,"needs_review",now_iso()))
            if args.bank:
                print(json.dumps(import_image_bank(conn,args.bank,config.data),ensure_ascii=False))
            conn.commit();result=PaperService(config,database).analyze(conn,pid)
            print(json.dumps({"paper_id":pid,"questions":result["created_questions"],"warnings":result["warnings"],"task":result.get("agent_task")},ensure_ascii=False))
        elif args.command=="import-bank":
            print(json.dumps(import_image_bank(conn,args.directory,config.data),ensure_ascii=False));conn.commit()
        elif args.command=="catalog":
            print(json.dumps(bank_catalog(conn,config.data,topics=args.topic,bank_id=args.bank_id,offset=args.offset,limit=args.limit,math_types=args.math_type,years=args.year,exclude_years=args.exclude_year),ensure_ascii=False,indent=2))
        elif args.command=="context":
            print(json.dumps(workspace_context(conn,config.data,args.paper_id),ensure_ascii=False,indent=2))
        else:
            snapshot=loop_snapshot(conn)
            active={r[0] for r in conn.execute('SELECT id FROM papers WHERE archived_at IS NULL')}
            tasks=[str(p) for p in (config.data/"tasks").glob("*/request.json") if p.parent.name in active and not conn.execute('SELECT id FROM agent_reports WHERE paper_id=?',(p.parent.name,)).fetchone()]
            attempts=[{"probe_id":p["id"],"prompt":p.get("prompt"),"attempts":p["attempts"]} for p in snapshot["probes"] if p['paper_id'] in active and p["status"] in ("awaiting_assessment","needs_supplement")]
            print(json.dumps({"tasks":tasks,"awaiting_assessment":attempts},ensure_ascii=False,indent=2))
    except Exception:
        conn.rollback();raise
    finally:
        conn.close()


if __name__=="__main__": main()
