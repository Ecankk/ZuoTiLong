"""Audit imported topic granularity without changing the personal database."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent_workspace import topic_audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / ".mathlens" / "mathlens.db")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    conn = sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        result = topic_audit(conn)
    finally:
        conn.close()
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(content + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "topics"}, ensure_ascii=False))
    else:
        print(content)


if __name__ == "__main__":
    main()
