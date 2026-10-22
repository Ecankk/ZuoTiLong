"""Create an isolated copy for browser submission tests; never submit to the personal DB."""
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server

destination=ROOT/'tmp/browser-fixture'
destination.mkdir(parents=True,exist_ok=True)
target=destination/'mathlens.db'
if target.exists():
    raise SystemExit('Test fixture already exists; preserve it or choose a new test directory.')
with sqlite3.connect(server.DB_PATH) as source,sqlite3.connect(target) as test:
    source.backup(test)
    row=test.execute('SELECT paper_id FROM agent_reports ORDER BY created_at DESC LIMIT 1').fetchone()
    pid=row[0]
    relative=test.execute('SELECT source_path FROM papers WHERE id=?',(pid,)).fetchone()[0]
    original=(ROOT/relative).resolve()
    copied=destination/'papers'/pid/original.name
    copied.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,copied)
    test.execute("UPDATE papers SET source_path=?,title='【隔离测试】真实试卷闭环' WHERE id=?",(str(copied.relative_to(ROOT)),pid))
    ids=[r[0] for r in test.execute('SELECT DISTINCT bank_id FROM diagnostic_probes WHERE paper_id=?',(pid,))]
    for bid in ids:
        resource=test.execute('SELECT question_path,analysis_path,answer_path FROM bank_resources WHERE bank_id=?',(bid,)).fetchone()
        for relative in resource:
            if not relative:continue
            output=destination/relative;output.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(server.DATA/relative,output)
    test.commit()
print(destination)
