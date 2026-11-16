"""Persistent, disposable navigation rows; never a source of learning evidence.

Library triggers identify affected bank rows. File change stamps are checked on
each read, hashing only changed files. Strict admission/reading still uses the
ordinary annotation/material validators. The private cache can be deleted.
"""
from contextlib import closing
import ctypes,json,os,sqlite3
from pathlib import Path

DIRECT={'bank_questions':'id','bank_resources':'bank_id','bank_identity':'bank_id',
        'question_annotation_links':'bank_id','imported_question_annotations':'bank_id'}
ANNOTATIONS={'question_annotations':'id','annotation_provenance':'annotation_id',
             'question_annotation_topics':'annotation_id','prepared_annotation_ids':'id'}
PAIRS={'bank_links','bank_identity_reviews'}
PACKAGES={'annotation_cache_state':'package_sha256','annotation_cache_packages':'sha256'}
CATALOG={'knowledge_catalog_state','knowledge_catalog_releases','knowledge_catalog_nodes','knowledge_catalog_redirects','knowledge_nodes'}

def initialize(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS navigation_changes(key TEXT PRIMARY KEY,version INTEGER NOT NULL)')
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in sorted((DIRECT.keys()|ANNOTATIONS.keys()|PAIRS|PACKAGES.keys()|CATALOG)&tables):
        columns=[r[1] for r in conn.execute('PRAGMA table_info('+table+')')]
        for action in ('INSERT','UPDATE','DELETE'):
            sides=('NEW',) if action=='INSERT' else ('OLD',) if action=='DELETE' else ('OLD','NEW')
            statements=[]
            for side in sides:
                if table in DIRECT:select='SELECT '+side+'.'+DIRECT[table]+',1'
                elif table in ANNOTATIONS:
                    select='SELECT bank_id,1 FROM question_annotation_links WHERE annotation_id='+side+'.'+ANNOTATIONS[table]+' AND true'
                elif table in PACKAGES:
                    select='SELECT bank_id,1 FROM imported_question_annotations WHERE package_sha256='+side+'.'+PACKAGES[table]+' AND true'
                elif table in PAIRS:
                    select='SELECT '+side+'.left_id,1 UNION SELECT '+side+'.right_id,1'
                else:select="SELECT '@catalog',1"
                # WHERE disambiguates UPSERT after INSERT SELECT, including UNION.
                statements.append('INSERT INTO navigation_changes(key,version) SELECT * FROM ('+select+') WHERE true ON CONFLICT(key) DO UPDATE SET version=version+1;')
            when=' WHEN '+' OR '.join('NEW."'+c+'" IS NOT OLD."'+c+'"' for c in columns) if action=='UPDATE' else ''
            name='nav_'+table+'_'+action.lower()
            sql='CREATE TRIGGER '+name+' AFTER '+action+' ON '+table+when+' BEGIN '+''.join(statements)+' END'
            old=conn.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(name,)).fetchone()
            if old and old[0]!=sql:conn.execute('DROP TRIGGER '+name);old=None
            if not old:conn.execute(sql)

if os.name=='nt':
    from ctypes import wintypes
    class BasicInfo(ctypes.Structure):
        _fields_=[(k,ctypes.c_longlong) for k in ('creation','access','write','change')]+[('attributes',wintypes.DWORD)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.GetFileInformationByHandleEx.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.GetFinalPathNameByHandleW.argtypes=[wintypes.HANDLE,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD]
    kernel.GetFinalPathNameByHandleW.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]

def file_stamp(path,root=None):
    try:
        stat=path.stat();change=stat.st_ctime_ns
        if os.name=='nt':
            # Windows st_ctime is birth time; NTFS ChangeTime also detects a
            # same-size replacement whose last-write time was restored.
            handle=kernel.CreateFileW(str(path),0x80,7,None,3,0,None)
            if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
            try:
                info=BasicInfo()
                if not kernel.GetFileInformationByHandleEx(handle,0,ctypes.byref(info),ctypes.sizeof(info)):raise ctypes.WinError(ctypes.get_last_error())
                change=info.change
                if root is not None:
                    buffer=ctypes.create_unicode_buffer(1024)
                    size=kernel.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0)
                    if not size:raise ctypes.WinError(ctypes.get_last_error())
                    if size>=len(buffer):
                        buffer=ctypes.create_unicode_buffer(size+1)
                        if not kernel.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0):raise ctypes.WinError(ctypes.get_last_error())
                    resolved=buffer.value.removeprefix('\\\\?\\')
                    if resolved.startswith('UNC\\'):resolved='\\\\'+resolved[4:]
                    resolved=os.path.normcase(resolved);base=os.path.normcase(str(root)).rstrip('\\')
                    if resolved!=base and not resolved.startswith(base+'\\'):raise ValueError('Navigation resource escapes its owning root')
            finally:kernel.CloseHandle(handle)
        elif root is not None and not path.resolve().is_relative_to(root):raise ValueError('Navigation resource escapes its owning root')
        return [stat.st_size,stat.st_mtime_ns,change,stat.st_ino]
    except FileNotFoundError:return None
    except OSError as exc:return ['unreadable',exc.errno,getattr(exc,'winerror',None)]

class NavigationIndex:
    FORMAT=3
    def __init__(self,config):self.config=config;self.path=config.data/'navigation-index.db'

    def open(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        conn=sqlite3.connect(self.path,timeout=15);conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS items(bank_id TEXT PRIMARY KEY,payload TEXT NOT NULL,materials TEXT NOT NULL,dependencies TEXT NOT NULL)')
        return conn

    def bank(self,conn,nodes,build,bank_ids=None):
        from app.desktop.control import checkpoint
        checkpoint()
        from app.bank.annotation_view import AnnotationReadView
        from app.bank import annotations
        from app.knowledge import catalog
        library=conn.execute('SELECT library_id FROM library_state WHERE singleton=1').fetchone()
        changes={r[0]:r[1] for r in conn.execute('SELECT key,version FROM navigation_changes')}
        identity=[library[0],str(self.config.library_dir.resolve()),self.config.library_database.stat().st_ino,self.FORMAT]
        selected=None
        if bank_ids is not None:
            groups=AnnotationReadView(conn,self.config.data)
            selected=set().union(*(groups.aliases(bid) for bid in bank_ids))
        where=' WHERE b.id IN ('+','.join('?' for _ in selected)+')' if selected else ''
        rows={r['id']:dict(r) for r in conn.execute('''SELECT b.id,b.source,b.collection_id,b.math_types_json,
            r.question_path,r.analysis_path,r.answer_path FROM bank_questions b LEFT JOIN bank_resources r ON r.bank_id=b.id'''+where,tuple(selected or ()))}
        roots={'library':self.config.library_dir.resolve(),'data':self.config.data.resolve()}
        def material_path(value):
            relative=Path(value)
            if relative.is_absolute() or relative.drive or '..' in relative.parts:raise ValueError('Invalid navigation resource path')
            base=roots['library' if relative.parts[0] in ('bank-assets','knowledge-sources') else 'data']
            return base/relative,base
        with closing(self.open()) as cache,cache:
            saved=cache.execute('SELECT payload FROM state WHERE id=1').fetchone()
            state=json.loads(saved[0]) if saved else {}
            if state.get('identity')!=identity:cache.execute('DELETE FROM items')
            query='SELECT * FROM items'+(' WHERE bank_id IN ('+','.join('?' for _ in selected)+')' if selected else '')
            old={r['bank_id']:dict(r) for r in cache.execute(query,tuple(selected or ()))} if state.get('identity')==identity else {}
            previous=state.get('changes',{}) if old else {}
            dirty={bid for bid in rows if bid not in old or changes.get(bid)!=previous.get(bid)}
            dirty.update(set(old)-rows.keys())
            if changes.get('@all')!=previous.get('@all'):dirty.update(rows)
            stamps={};material_cache={};file_changed=set()
            watched={}
            for bid,row in rows.items():
                for role in ('question','answer','analysis'):
                    path=row[role+'_path']
                    if path:watched.setdefault(path,set()).add(bid)
            for path,bids in watched.items():
                checkpoint()
                absolute,owner=material_path(path);stamps[path]=file_stamp(absolute,owner)
                if stamps[path]!=state.get('files',{}).get(path):file_changed.update(bids)
            for bid,row in old.items():
                actual=json.loads(row['materials']);material_cache[bid]=actual
            dirty.update(file_changed)
            # Material/source changes invalidate the whole confirmed alias group.
            affected={json.loads(old[b]['payload'])['entity_id'] for b in dirty if b in old}
            dirty.update(bid for bid,row in old.items() if json.loads(row['payload'])['entity_id'] in affected)
            view=AnnotationReadView(conn,self.config.data)
            names={n['id']:n['name'] for n in nodes}
            if changes.get('@catalog')!=previous.get('@catalog'):
                for bid,row in old.items():
                    deps=json.loads(row['dependencies']);item=json.loads(row['payload'])
                    try:
                        current=annotations.concept_dependencies(conn,list(deps),read_view=view)
                        resolved={k:view.resolve(k) for k in deps}
                        same=set(current)==set(resolved.values()) and all(current.get(resolved[k])==v for k,v in deps.items())
                    except ValueError:same=False
                    if not same or item['status']=='outdated':dirty.add(bid)
            for bid in list(dirty):
                if bid in rows:dirty.update(view.aliases(bid))
            # Reuse validated bytes only when neither their owning row nor the
            # filesystem changed; definition-only edits need no image rehash.
            for bid,actual in material_cache.items():
                if bid not in file_changed and changes.get(bid)==previous.get(bid):view._materials[bid]=actual
            items=[]
            for bid,row in rows.items():
                checkpoint()
                if bid in dirty:
                    item,deps=build(conn,row,nodes,view)
                    try:actual=view.materials(bid)
                    except (ValueError,OSError):actual={}
                    cache.execute('INSERT OR REPLACE INTO items VALUES(?,?,?,?)',(bid,catalog.encode(item),catalog.encode(actual),catalog.encode(deps)))
                    material_cache[bid]=actual
                else:
                    item=json.loads(old[bid]['payload'])
                    from app.services.knowledge_links import public_topics
                    item['topics']=public_topics(item['topics'],names,view.resolve)
                if row['source']!='本地示例题库':items.append({k:v for k,v in item.items() if k!='_annotation'})
            for bid in set(old)-rows.keys():cache.execute('DELETE FROM items WHERE bank_id=?',(bid,))
            files=dict(stamps)
            for path,bids in watched.items():
                if not bids.intersection(dirty):continue
                absolute,owner=material_path(path);files[path]=file_stamp(absolute,owner)
                if files[path]!=stamps[path]:raise ValueError('题库材料正在变化，请稍后重新读取关联')
            if selected is not None:
                changes={**state.get('changes',{}),**{k:v for k,v in changes.items() if k in selected}}
                files={**state.get('files',{}),**files}
            value=catalog.encode(dict(identity=identity,changes=changes,files=files))
            if not saved or saved[0]!=value:cache.execute('INSERT OR REPLACE INTO state VALUES(1,?)',(value,))
            return sorted(items,key=lambda i:i['bank_id'])
