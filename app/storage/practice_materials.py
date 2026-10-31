"""Immutable selected bank materials; independent of later library updates."""
from pathlib import Path
import hashlib,json,re,tempfile,time
from app.bank.annotations import materials
from app.knowledge.catalog import digest
from app.storage.boundaries import material_path

ROLES=('question','analysis','answer')


def _publish(stage,target):
    # Windows scanners may briefly hold files in a newly completed directory.
    # Retry the atomic rename, never expose a partially copied destination.
    for attempt in range(5):
        if target.exists():return
        try:
            stage.rename(target)
            return
        except PermissionError:
            if target.exists():return
            if attempt==4:raise
            time.sleep(.05*(attempt+1))


def _folder(data,key):
    if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{64}',key):raise ValueError('练习材料快照标识无效')
    base=Path(data).resolve();root=(base/'practice-materials').resolve();folder=(root/key).resolve()
    if not root.is_relative_to(base):raise ValueError('练习材料目录越界')
    if not folder.is_relative_to(root):raise ValueError('练习材料快照路径越界')
    return root,folder


def load(data,key,expected_sha256,roles=None):
    if roles is not None and not set(roles).issubset(ROLES):raise ValueError('练习材料角色无效')
    _,folder=_folder(data,key)
    try:
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        if digest(manifest)!=expected_sha256 or manifest.get('format')!='mathlens.practice-materials/v1':
            raise ValueError('练习材料快照清单已变化')
        resources=manifest['resources'];original={}
        if not isinstance(resources,dict) or 'question' not in resources or not set(resources).issubset(ROLES):
            raise ValueError('练习材料快照资源不完整')
        for role,item in resources.items():
            selected=roles is None or role in roles
            actual_sha=item['image_sha256'] if not selected else None
            if selected and item['image_file']:
                path=(folder/item['image_file']).resolve()
                if path.parent!=folder or not path.is_file():raise ValueError('练习材料快照图片缺失或越界')
                actual_sha=hashlib.sha256(path.read_bytes()).hexdigest()
                if actual_sha!=item['image_sha256']:raise ValueError('练习材料快照图片已变化')
            if selected and digest({'text':item['text'],'image_sha256':actual_sha})!=item['sha256']:
                raise ValueError('练习材料快照内容不一致')
            original[role]={'text':item['text'],'path':item['source_path'],
                            'image_sha256':actual_sha,'sha256':item['sha256']}
        if digest(original)!=manifest['material_revision'] or resources['question']['sha256']!=manifest['content_revision']:
            raise ValueError('练习材料快照版本不一致')
    except (OSError,KeyError,TypeError,json.JSONDecodeError) as error:
        raise ValueError('练习材料快照缺失或损坏，请恢复对应备份') from error
    return manifest


def image_path(data,binding,role):
    if role not in ROLES:raise ValueError('练习材料角色无效')
    manifest=load(data,binding['snapshot_key'],binding['snapshot_sha256'],(role,))
    item=manifest['resources'].get(role)
    if not item or not item['image_file']:raise ValueError('此练习版本没有对应图片')
    return _folder(data,binding['snapshot_key'])[1]/item['image_file']


def freeze(conn,data,binding):
    actual=materials(conn,data,binding['bank_id'])
    if digest(actual)!=binding['material_revision'] or actual['question']['sha256']!=binding['content_revision']:
        raise ValueError('练习材料在选题保存前已变化')
    key=digest({'bank_id':binding['bank_id'],'material_revision':binding['material_revision']})
    root,target=_folder(data,key);root.mkdir(parents=True,exist_ok=True)
    manifest={'format':'mathlens.practice-materials/v1','bank_id':binding['bank_id'],
              'material_revision':binding['material_revision'],'content_revision':binding['content_revision'],'resources':{}}
    blobs={}
    for role,item in actual.items():
        filename=None
        if item['path']:
            source=material_path(data,item['path']).resolve()
            raw=source.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=item['image_sha256']:raise ValueError('题库图片在保存快照时已变化')
            suffix=source.suffix.lower()
            if suffix not in ('.png','.jpg','.jpeg','.webp'):raise ValueError('练习快照图片格式不支持')
            filename=role+suffix;blobs[filename]=raw
        manifest['resources'][role]={k:item[k] for k in ('text','image_sha256','sha256')}
        manifest['resources'][role].update(source_path=item['path'],image_file=filename)
    expected=digest(manifest)
    if not target.exists():
        # Publish a complete directory; failed DB transactions can reuse this
        # verified, unreferenced cache. Never overwrite a previous snapshot.
        with tempfile.TemporaryDirectory(prefix='material-',dir=root) as temporary:
            stage=Path(temporary)/'complete';stage.mkdir()
            for name,raw in blobs.items():(stage/name).write_bytes(raw)
            (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True),encoding='utf-8')
            if not stage.resolve().is_relative_to(root):raise ValueError('临时快照路径越界')
            _publish(stage,target)
    verified=load(data,key,expected)
    if verified['bank_id']!=binding['bank_id']:raise ValueError('练习快照来源不一致')
    return {**binding,'snapshot_key':key,'snapshot_sha256':expected,'material_manifest':manifest}
