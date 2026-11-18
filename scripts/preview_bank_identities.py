"""只读预演旧题库同题证据；不初始化数据库，不支持确认或写实体边。"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.bank.identity_preview import preview


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',required=True,type=Path,help='显式指定通用库目录')
    parser.add_argument('--dry-run',action='store_true',help='本命令始终只读')
    parser.add_argument('--completeness',type=Path,help='可选：bank_id到完整性证明的JSON映射，含question_sha256及stem/options/images/target=true、evidence')
    parser.add_argument('--report',type=Path,help='不含题面正文的JSON报告，必须在库目录外')
    args=parser.parse_args()
    if args.report and args.report.resolve().is_relative_to(args.library.resolve()):parser.error('报告必须放在通用库目录外')
    proofs=json.loads(args.completeness.read_text(encoding='utf8')) if args.completeness else None
    if proofs is not None and (not isinstance(proofs,dict) or any(not isinstance(v,dict) for v in proofs.values())):parser.error('完整性证明须为bank_id到对象的映射')
    result=preview(args.library,completeness=proofs)
    output=json.dumps(result,ensure_ascii=False,indent=2)
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(output,encoding='utf8')
    print(output)


if __name__=='__main__':main()
