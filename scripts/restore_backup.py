"""Restore into a NEW local data directory; existing data is never replaced."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_maintenance import restore

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path);parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(restore(args.archive,args.destination),ensure_ascii=False))
