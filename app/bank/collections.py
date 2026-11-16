"""One visible collection per question; source provenance remains independent."""
DEFAULTS=(('zhenti','真题','exam',10),('zhangyu-1000-basic','张宇1000题基础篇','book',15),
          ('zhangyu-1000','张宇1000题','book',20),
          ('zhangyu-1000-tests','张宇1000题测试卷','book',25),
          ('other','其他','other',30),('example','示例','example',40))
LEGACY=('数学一真题图片库','数学二真题图片库','数学三真题图片库')

DEFAULTS=DEFAULTS+(('lilin-880','\u674e\u6797 880\u9898','book',30),('wuzhongxiang-yanxuan','\u6b66\u5fe0\u7965\u4e25\u9009','book',31),('cxy-1k','1k\u9898\u6e90','book',32))

def initial(row,standard=None):
    if row['source']=='本地示例题库':return 'example'
    if row['source'] in LEGACY:return 'zhenti'
    if standard and (standard['source_id'],standard['exam_year'],standard['math_type'])==('S02',2026,1) and standard['number'] in range(1,23):return 'zhenti'
    return 'other'

def assign_legacy(conn):
    conn.execute("UPDATE bank_questions SET collection_id='example' WHERE source='本地示例题库'")
    conn.execute("UPDATE bank_questions SET collection_id='zhenti' WHERE source IN (?,?,?)",LEGACY)
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'bank_source_records' in tables:
        conn.execute("""UPDATE bank_questions SET collection_id='zhenti' WHERE id IN
            (SELECT bank_id FROM bank_source_records WHERE source_id='S02'
             AND json_extract(record_json,'$.exam_year')=2026 AND json_extract(record_json,'$.math_type')=1
             AND json_extract(record_json,'$.number') BETWEEN 1 AND 22)""")

def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS bank_collections(
        id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('exam','book','other','example')),
        sort_order INTEGER NOT NULL)''')
    conn.executemany('INSERT OR IGNORE INTO bank_collections VALUES(?,?,?,?)',DEFAULTS)
    columns={r[1] for r in conn.execute('PRAGMA table_info(bank_questions)')}
    if 'collection_id' not in columns:
        conn.execute("ALTER TABLE bank_questions ADD COLUMN collection_id TEXT NOT NULL DEFAULT 'other'")
        assign_legacy(conn)
    conn.execute('CREATE INDEX IF NOT EXISTS idx_bank_collection ON bank_questions(collection_id)')
    for action in ('INSERT','UPDATE OF collection_id'):
        conn.execute('CREATE TRIGGER IF NOT EXISTS bank_collection_'+action.split()[0].lower()+' BEFORE '+action+''' ON bank_questions
            WHEN NOT EXISTS(SELECT 1 FROM bank_collections WHERE id=NEW.collection_id)
            BEGIN SELECT RAISE(ABORT,'Unknown bank collection'); END''')
    conn.execute('''CREATE TRIGGER IF NOT EXISTS bank_collection_delete BEFORE DELETE ON bank_collections
        WHEN EXISTS(SELECT 1 FROM bank_questions WHERE collection_id=OLD.id)
        BEGIN SELECT RAISE(ABORT,'Collection still contains questions'); END''')
    conn.execute('''CREATE TRIGGER IF NOT EXISTS bank_collection_rename BEFORE UPDATE OF id ON bank_collections
        WHEN NEW.id!=OLD.id AND EXISTS(SELECT 1 FROM bank_questions WHERE collection_id=OLD.id)
        BEGIN SELECT RAISE(ABORT,'Collection still contains questions'); END''')

def require(conn,collection):
    from app.storage.boundaries import table_exists
    present=table_exists(conn,'bank_collections')
    valid=bool(conn.execute('SELECT 1 FROM bank_collections WHERE id=?',(collection,)).fetchone()) if present else collection in {v[0] for v in DEFAULTS}
    if not valid:raise ValueError('Unknown collection: '+str(collection))

def membership(conn,bid):
    return conn.execute('SELECT collection_id FROM bank_questions WHERE id=?',(bid,)).fetchone()[0]
