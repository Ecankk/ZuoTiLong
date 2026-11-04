"""Build/refresh disposable navigation before distributing an upgraded workspace."""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--initialize',action='store_true',help='备份后显式执行现有数据库结构升级，再构建索引')
    args=parser.parse_args()
    from app.storage.boundaries import workspace_config
    from dataclasses import replace
    from app.storage.database import Database
    from app.services.knowledge_links import KnowledgeLinksService
    config=replace(workspace_config(args.workspace.resolve()),library=args.library.resolve())
    if not config.database.is_file() or not config.library_database.is_file():raise ValueError('Initialize/migrate the workspace and library first')
    if args.initialize:Database(config).initialize()
    start=time.perf_counter()
    summary=KnowledgeLinksService(config,Database(config)).summary()
    print(json.dumps(dict(cache=str(config.data/'navigation-index.db'),elapsed_seconds=time.perf_counter()-start,
        source_records=summary['source_records'],total_bank=summary['total_bank'],authoritative_databases_written=args.initialize),ensure_ascii=False))

if __name__=='__main__':main()
