"""Preview and confirm public annotation evidence; never modify the source workspace."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.provenance_upgrade import upgrade


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--workspace',type=Path,required=True,help='包含旧执行数据库的维护工作区')
    group=parser.add_mutually_exclusive_group();group.add_argument('--dry-run',action='store_true');group.add_argument('--confirm')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    marker=args.workspace/'workspace.json'
    name=json.loads(marker.read_text(encoding='utf8')).get('database','learning.db') if marker.is_file() else 'learning.db'
    if not isinstance(name,str) or Path(name).name!=name:raise ValueError('旧工作区数据库名称不合法')
    result=upgrade(args.library,args.workspace/name,confirm=args.confirm)
    output=json.dumps(result,ensure_ascii=False,indent=2)
    if args.report:args.report.write_text(output,encoding='utf8')
    print(output)


if __name__=='__main__':main()
