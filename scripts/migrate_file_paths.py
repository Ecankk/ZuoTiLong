"""Preview, back up and confirm owned file path upgrades; never run on startup."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import AppConfig
from app.storage.path_upgrade import upgrade

def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group();group.add_argument('--dry-run',action='store_true');group.add_argument('--confirm')
    p.add_argument('--report',type=Path)
    a=p.parse_args();result=upgrade(AppConfig.from_env(),a.confirm)
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if a.report:a.report.write_text(text,encoding='utf8')
    print(text)

if __name__=='__main__':main()
