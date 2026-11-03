"""Owned file references. Absolute paths exist only at runtime boundaries."""
from pathlib import Path, PureWindowsPath


def resolve_file(root, relative):
    text=str(relative).replace('\\','/')
    if Path(text).is_absolute() or PureWindowsPath(text).drive or '..' in text.split('/'):
        raise ValueError('文件引用必须为所属目录内的相对路径')
    path=(Path(root)/text).resolve()
    if not path.is_relative_to(Path(root).resolve()):raise ValueError('文件引用越界')
    return path


def relative_file(root, path):
    relative=Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    resolve_file(root,relative)
    return relative


def paper_path(data, value, legacy_root=None):
    """Read old contained references until the explicit upgrade is confirmed."""
    text=str(value).replace('\\','/')
    if text.startswith('papers/'):
        return resolve_file(data,text)
    old=Path(value) if Path(value).is_absolute() else Path(legacy_root or data)/value
    return resolve_file(data,relative_file(data,old))


def connection_data(conn):
    return Path(next(r[2] for r in conn.execute('PRAGMA database_list') if r[1]=='main')).parent


def session_paths(value,data,*,unpack=False):
    from app.storage.boundaries import library_root
    roots={'data':Path(data),'library':library_root(data)}
    def walk(v):
        if isinstance(v,dict):
            if unpack and set(v)=={'$file','root'}:
                return str(resolve_file(roots[v['root']],v['$file']))
            return {k:walk(x) for k,x in v.items()}
        if isinstance(v,list):return [walk(x) for x in v]
        if not unpack and isinstance(v,str) and Path(v).is_absolute() and '\n' not in v:
            owners=('library','data') if roots['library'].resolve()!=roots['data'].resolve() else ('data','library')
            for owner in owners:
                root=roots[owner]
                if Path(v).resolve().is_relative_to(root.resolve()):
                    return {'$file':relative_file(root,v),'root':owner}
        return v
    return walk(value)
