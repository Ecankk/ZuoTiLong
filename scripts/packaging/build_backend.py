"""Build the locked onedir backend and the D/E sidecar staging layout."""
import argparse
from email.parser import BytesParser
import hashlib
from importlib.metadata import version
import json,os,platform,re,shutil,struct,subprocess,sys
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[2]


def run(args):
    build=ROOT/'build';stage=build/'desktop-stage'
    if os.name!='nt' or sys.version_info[:3]!=(3,12,10) or struct.calcsize('P')!=8 or sys.prefix==sys.base_prefix:
        raise RuntimeError('Use a fresh official Python 3.12.10 x64 venv on Windows')
    wheels=json.loads((Path(__file__).with_name('wheels-win-x64-py312.json')).read_text(encoding='utf8'))['wheels']
    for w in wheels:
        if version(w['name'])!=w['version']:raise ValueError('Installed version differs from lock: '+w['name'])
        path=args.wheelhouse/w['filename']
        with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        if sha!=w['sha256']:raise ValueError('Wheel hash differs from lock: '+path.name)
    subprocess.run([sys.executable,'-m','pip','check'],check=True)
    # No build-time app import may fall back to developer data.
    os.environ.update(MATHLENS_DATA_DIR=str(build/'build-decoy-data'),MATHLENS_LIBRARY_DIR=str(build/'build-decoy-library'),MATHLENS_CODEX_BIN=str(build/'missing-codex.exe'),MATHLENS_DEMO='0')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(build/'pyinstaller-dist'),
        '--workpath',str(build/'pyinstaller-work'),str(Path(__file__).with_name('mathlens-backend.spec'))],cwd=ROOT,check=True)
    if stage.exists():
        if stage.is_symlink() or stage.resolve().parent!=build.resolve() or not (stage/'build-manifest.json').is_file():raise ValueError('Refuse to replace an unowned stage directory')
        shutil.rmtree(stage)
    stage.mkdir();backend=stage/'backend';resources=stage/'resources'
    shutil.copytree(build/'pyinstaller-dist/mathlens-backend',backend)
    shutil.copytree(ROOT/'dist',resources/'dist')
    # copy_metadata keeps runtime METADATA but its license payload belongs in
    # the contract's resources/licenses tree, not beside the executable.
    runtime_licenses=resources/'licenses'/'runtime-dist-info';runtime_licenses.mkdir(parents=True,exist_ok=True)
    for path in list((backend/'_internal').rglob('*')):
        if not path.is_file() or not re.search(r'^(license|licence|copying|notice)([^/]*)(\.[^/]*)?$',path.name,re.I):continue
        target=runtime_licenses/path.relative_to(backend/'_internal');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target);path.unlink()
    sys.path.insert(0,str(ROOT));from app.agent.methods import SKILLS
    for name in SKILLS:
        relative=Path('.agents/skills')/('mathlens-'+name)/'SKILL.md';target=resources/relative
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,target)
    (resources/'docs').mkdir()
    for name in ('agent-workflow.md','question-sources.md','bank-source-interface.md'):shutil.copyfile(ROOT/'docs'/name,resources/'docs'/name)
    if args.seed:
        if not (args.seed/'manifest.json').is_file():raise ValueError('--seed must be an approved seed with manifest.json')
        shutil.copytree(args.seed,resources/'library-seed');synthetic=False
    else:
        from synthetic_seed import create
        create(resources/'library-seed');synthetic=True
    licenses=resources/'licenses';licenses.mkdir(exist_ok=True);notices=[]
    for w in wheels:
        with zipfile.ZipFile(args.wheelhouse/w['filename']) as archive:
            metadata=BytesParser().parsebytes(archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA') and len(n.split('/'))==2)))
            notices.append(w['name']+' '+w['version']+'\n'+str(metadata.get('License-Expression') or metadata.get('License') or 'See included license files')+'\n')
            for name in archive.namelist():
                if not re.search(r'(^|/)(license|licence|copying|notice)([^/]*)(\.[^/]*)?$',name,re.I):continue
                # Retain the wheel's relative license layout without extraction paths.
                parts=Path(name).parts
                if '..' in parts or Path(name).is_absolute():raise ValueError('Unsafe license archive path')
                target=licenses/w['name']/Path(*parts);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(name))
    notices.append('PyMuPDF is distributed under its included AGPL license. Upstream source: https://github.com/pymupdf/PyMuPDF .\nMathLens project license/source availability: see project LICENSE and the distribution source URL.\n')
    shutil.copytree(Path(__file__).with_name('licenses'),licenses/'GNU')
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():shutil.copyfile(python_license,licenses/'Python-LICENSE.txt')
    if (ROOT/'licenses').is_dir():shutil.copytree(ROOT/'licenses',licenses/'MathLens-notices')
    (licenses/'THIRD-PARTY-NOTICES.txt').write_text('\n'.join(notices),encoding='utf8')
    if (ROOT/'LICENSE').is_file():shutil.copyfile(ROOT/'LICENSE',licenses/'LICENSE-MathLens.txt')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    if not dirty:
        source=licenses/'source';source.mkdir()
        subprocess.run(['git','archive','--format=zip','--output',str(source/('mathlens-'+commit+'.zip')),commit],cwd=ROOT,check=True)
        with (licenses/'THIRD-PARTY-NOTICES.txt').open('a',encoding='utf8') as notice:notice.write('\nCorresponding MathLens source for this build: source/mathlens-'+commit+'.zip\n')
    summary=dict(schema='mathlens.desktop-build/v1',commit=commit,python=platform.python_version(),pyinstaller=version('pyinstaller'),pillow=version('pillow'),
        lock_sha256=hashlib.sha256(Path(__file__).with_name('requirements-win-x64-py312.lock').read_bytes()).hexdigest(),synthetic_seed=synthetic,dirty_source=dirty,
        backend_bytes=sum(p.stat().st_size for p in backend.rglob('*') if p.is_file()),resource_bytes=sum(p.stat().st_size for p in resources.rglob('*') if p.is_file()))
    (stage/'build-manifest.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(json.dumps(dict(stage=str(stage),**summary)))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--wheelhouse',type=Path,default=ROOT/'build/desktop-wheelhouse');parser.add_argument('--seed',type=Path)
    run(parser.parse_args())
