"""Retain immutable source evidence in the same backup scope as the catalogue."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import shutil
import time
from app.storage.boundaries import library_root


def publish_evidence(staging, destination):
    """Windows scanners may briefly deny directory rename; never copy-publish."""
    for attempt in range(5):
        try:
            staging.replace(destination)
            return
        except PermissionError as exc:
            if getattr(exc,'winerror',None) not in (5,32,33) or attempt==4:
                raise
            time.sleep(.05*(2**attempt))


def preserve_supplement(data, directory, source_version_id):
    from app.knowledge.candidates import read_supplement
    source = Path(directory).resolve()
    prepared = read_supplement(source)
    base = library_root(data)
    parent = base / 'knowledge-sources'
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / source_version_id
    if not destination.resolve().is_relative_to(base.resolve()):
        raise ValueError('来源证据目录超出本地资料范围')
    if destination.exists():
        saved = read_supplement(destination)
        if saved != prepared:
            raise ValueError('已归档来源证据与固定候选版本不一致，不能覆盖')
        return destination.relative_to(base).as_posix()
    with TemporaryDirectory(dir=parent, prefix='.staging-') as temporary:
        staging = Path(temporary)
        shutil.copyfile(source / 'index.json', staging / 'index.json')
        for reference in prepared['metadata']['references']:
            relative = reference['path']
            raw = (source / relative).read_bytes()
            if hashlib.sha256(raw).hexdigest() != reference['sha256']:
                raise ValueError('来源证据在归档前变化，请固定版本后重新导入')
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        if read_supplement(staging) != prepared:
            raise ValueError('来源清单在归档期间变化，未保存候选')
        # An immutable, complete evidence folder may outlive a database rollback.
        # It is harmless without a source row and is reused on the next import.
        publish_evidence(staging,destination)
        return destination.relative_to(base).as_posix()
