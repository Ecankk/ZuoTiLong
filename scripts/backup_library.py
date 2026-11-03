"""Back up a shared library before curation; restore only into a new directory."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.library_backup import backup_library,restore_library


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',type=Path,required=True,help='明确的库目录；恢复时为不存在的新目录')
    parser.add_argument('--workspace',type=Path,action='append',default=[],help='额外需检查写保护的维护工作区，可重复')
    parser.add_argument('--restore',type=Path,help='恢复题库ZIP到 --library，不覆盖已有库')
    args=parser.parse_args()
    result=restore_library(args.restore,args.library) if args.restore else backup_library(args.library,workspaces=args.workspace)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
