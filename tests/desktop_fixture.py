from contextlib import closing
import hashlib,json,sqlite3
from pathlib import Path
from types import SimpleNamespace
from app.agent.methods import SKILLS
from app.config import AppConfig
from app.storage.database import Database
from app.version import VERSION


def resources(base):
    root=base/'只读 安装 resources';(root/'dist').mkdir(parents=True)
    (root/'dist/index.html').write_text('<html>synthetic desktop</html>',encoding='utf8')
    for name in SKILLS:
        file=root/'.agents/skills'/('mathlens-'+name)/'SKILL.md';file.parent.mkdir(parents=True,exist_ok=True);file.write_text('Synthetic method '+name,encoding='utf8')
    (root/'docs').mkdir()
    for name in ('agent-workflow.md','question-sources.md','bank-source-interface.md'):(root/'docs'/name).write_text('Synthetic document',encoding='utf8')
    build=base/'build';config=AppConfig(base,build/'workspace',root/'dist',build/'workspace/learning.db',library=build/'library')
    db=Database(config);db.initialize()
    from PIL import Image
    (config.library_dir/'bank-assets').mkdir();Image.new('RGB',(4,4),'white').save(config.library_dir/'bank-assets/question.png')
    with db.session(write=True,library_write=True) as conn:
        conn.execute("INSERT INTO bank_questions(id,source,stem,answer,created_at) VALUES('synthetic','fixture','Compute $1+1$.','2','now')")
        conn.execute("INSERT INTO bank_resources VALUES('synthetic','{}','bank-assets/question.png',NULL,NULL)")
    seed=root/'library-seed';seed.mkdir()
    import shutil
    shutil.copytree(config.library_dir/'bank-assets',seed/'bank-assets')
    with closing(sqlite3.connect(config.library_database)) as old,closing(sqlite3.connect(seed/'library.db')) as target:old.backup(target)
    refresh_manifest(root);return root


def refresh_manifest(root):
    seed=root/'library-seed'
    with closing(sqlite3.connect((seed/'library.db').as_uri()+'?mode=ro',uri=True)) as conn:
        identity=conn.execute('SELECT library_id,revision FROM library_state').fetchone()
    files={p.relative_to(seed).as_posix():dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),size=p.stat().st_size) for p in seed.rglob('*') if p.is_file() and p.name!='manifest.json'}
    value=dict(schema='mathlens.library-seed/v1',release_id='synthetic-1',min_app_version=VERSION,library_id=identity[0],library_revision=identity[1],counts=dict(questions=1,ready=0),collections=[dict(id='other',total=1,ready=0)],files=files)
    (seed/'manifest.json').write_text(json.dumps(value),encoding='utf8')


def arguments(base,root):
    return SimpleNamespace(resource_root=str(root),data_dir=str(base/'用户 data/workspaces/default'),library_dir=str(base/'用户 data/library'),dist_dir=None,launch_nonce='a'*64)
