"""Repair saved question regions using existing local OCR cache only."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.config import AppConfig
from app.storage.boundaries import workspace_config
from app.storage.restore_regions import restore

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paper',required=True);parser.add_argument('--data',type=Path)
    choice=parser.add_mutually_exclusive_group();choice.add_argument('--dry-run',action='store_true');choice.add_argument('--confirm')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args();config=workspace_config(args.data,ROOT) if args.data else AppConfig.from_env(ROOT)
    value=restore(config,args.paper,args.confirm);text=json.dumps(value,ensure_ascii=False,indent=2)
    if args.report:args.report.write_text(text,encoding='utf8')
    print(text)

if __name__=='__main__':main()
