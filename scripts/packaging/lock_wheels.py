"""Record a resolved, wheel-only Windows x64 CPython 3.12 environment."""
import argparse
from email.parser import BytesParser
import hashlib,json,re
from pathlib import Path
import zipfile


def normalized(name):return re.sub('[-_.]+','-',name).lower()


def record(wheelhouse,output):
    wheels=[];seen=set()
    for path in sorted(wheelhouse.glob('*.whl')):
        with zipfile.ZipFile(path) as archive:
            metadata=[n for n in archive.namelist() if n.endswith('.dist-info/METADATA') and len(n.split('/'))==2]
            if len(metadata)!=1:raise ValueError('Missing unique wheel metadata: '+path.name)
            value=BytesParser().parsebytes(archive.read(metadata[0]));name=normalized(value['Name']);version=value['Version']
        if name in seen:raise ValueError('Use a clean wheelhouse; duplicate '+name)
        seen.add(name)
        with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        wheels.append(dict(name=name,version=version,filename=path.name,sha256=sha,size=path.stat().st_size))
    if not wheels:raise ValueError('No wheels')
    wheels.sort(key=lambda x:x['name']);output.mkdir(parents=True,exist_ok=True)
    lock='# Windows x64 / CPython 3.12.10; resolved runtime + build tools.\n# Install only binary wheels with --require-hashes. See README.md.\n'
    lock+=''.join(w['name']+'=='+w['version']+' --hash=sha256:'+w['sha256']+'\n' for w in wheels)
    (output/'requirements-win-x64-py312.lock').write_text(lock,encoding='utf8')
    (output/'wheels-win-x64-py312.json').write_text(json.dumps(dict(schema='mathlens.build-wheels/v1',python='3.12.10',platform='win_amd64',wheels=wheels),indent=2)+'\n',encoding='utf8')
    return wheels


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--wheelhouse',type=Path,required=True);parser.add_argument('--output',type=Path,default=Path(__file__).parent)
    args=parser.parse_args();print('Locked',len(record(args.wheelhouse,args.output)),'wheels')
