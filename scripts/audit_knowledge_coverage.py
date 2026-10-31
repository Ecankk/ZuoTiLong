"""Read-only shared-catalogue audit. Output defaults to Git-ignored tmp/."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.knowledge.coverage import read_report, markdown
from app.config import AppConfig
from app.storage.boundaries import workspace_config,connect_workspace


def main():
    parser = argparse.ArgumentParser(description='核对目录、来源处置与当前就绪题覆盖；不评价学生')
    parser.add_argument('--data', type=Path, default=AppConfig.from_env(ROOT).data)
    parser.add_argument('--output', type=Path, default=ROOT/'tmp/source-audits/knowledge-coverage')
    args = parser.parse_args()
    data = args.data.resolve()
    config = workspace_config(data,ROOT)
    database = config.database
    output = args.output.resolve()
    if output.is_relative_to(data):
        parser.error('审查输出不能写入学习资料目录')
    if not database.is_file():
        parser.error('资料数据库不存在；只读核对不会创建空库')
    with closing(connect_workspace(config,readonly=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')
        report = read_report(conn, data)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    output.with_suffix('.md').write_text(markdown(report), encoding='utf-8')
    print(json.dumps({'summary': report['summary'], 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
