"""One invented question, no private history. For build/sidecar smoke only."""
from contextlib import closing
import hashlib,json,sqlite3,tempfile
from pathlib import Path


def create(destination):
    from app.config import AppConfig
    from app.storage.database import Database
    from app.version import VERSION
    from PIL import Image
    if destination.exists():raise ValueError('Synthetic seed target must be new')
    destination.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='seed-build-',dir=destination.parent) as folder:
        base=Path(folder);config=AppConfig(base,base/'workspace',base/'dist',base/'workspace/learning.db',library=base/'library')
        db=Database(config);db.initialize()
        with db.session(write=True,library_write=True) as conn:
            conn.execute("INSERT INTO bank_questions(id,source,stem,answer,created_at) VALUES('packaging-example','packaging synthetic','Compute $1+1$.','2','now')")
            conn.execute("INSERT INTO bank_resources VALUES('packaging-example','{}','bank-assets/example.png',NULL,NULL)")
        with closing(sqlite3.connect(config.library_database)) as source,closing(sqlite3.connect(destination/'library.db')) as target:source.backup(target)
    (destination/'bank-assets').mkdir();Image.new('RGB',(8,8),'white').save(destination/'bank-assets/example.png')
    with closing(sqlite3.connect(destination/'library.db')) as conn:identity=conn.execute('SELECT library_id,revision FROM library_state').fetchone()
    files={p.relative_to(destination).as_posix():dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),size=p.stat().st_size) for p in destination.rglob('*') if p.is_file()}
    manifest=dict(schema='mathlens.library-seed/v1',release_id='packaging-synthetic-only',min_app_version=VERSION,
        library_id=identity[0],library_revision=identity[1],counts=dict(questions=1,ready=0),collections=[dict(id='other',total=1,ready=0)],files=files)
    (destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
