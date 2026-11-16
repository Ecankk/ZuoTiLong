"""Desktop path selection never consults inherited MATHLENS path variables."""
import json
import os
from pathlib import Path
import re
import sys
from app.config import AppConfig
from app.desktop.protocol import DesktopError


def settings(args):
    def absolute(value,name):
        if not value or not Path(value).is_absolute():raise DesktopError('invalid_path',name+'必须为绝对路径',2)
        return Path(value).resolve()
    root=absolute(args.resource_root,'resource-root');data=absolute(args.data_dir,'data-dir');library=absolute(args.library_dir,'library-dir')
    dist=absolute(args.dist_dir,'dist-dir') if args.dist_dir else root/'dist'
    if any(p.exists() and not p.is_dir() for p in (data,library)):raise DesktopError('invalid_path','数据和题库位置必须为目录',2)
    if not re.fullmatch('[0-9a-f]{64}',args.launch_nonce or ''):raise DesktopError('invalid_path','launch-nonce必须为64位小写十六进制',2)
    owners=[root]+([Path(sys.executable).resolve().parent] if getattr(sys,'frozen',False) else [])
    if any(p.is_relative_to(owner) or owner.is_relative_to(p) for p in (data,library) for owner in owners) or data.is_relative_to(library) or library.is_relative_to(data):
        raise DesktopError('invalid_path','数据、题库和安装资源目录不能相互包含',2)
    # Set before importing services/reading workspace helpers; never call from_env.
    os.environ.update(MATHLENS_DATA_DIR=str(data),MATHLENS_LIBRARY_DIR=str(library),MATHLENS_DIST_DIR=str(dist),MATHLENS_DEMO='0')
    name='learning.db';marker=data/'workspace.json'
    if marker.is_file():
        try:
            saved=json.loads(marker.read_text(encoding='utf8'));name=saved['database'];location=Path(saved['library'])
            if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name:raise ValueError()
            actual=(location if location.is_absolute() else data/location).resolve()
            if actual!=library:raise DesktopError('workspace_location_mismatch','工作区记录的通用库与所选位置不一致',12)
            if not (data/name).is_file():raise DesktopError('workspace_incomplete','工作区数据库缺失，请重新定位或恢复',12)
        except (ValueError,KeyError,TypeError):raise DesktopError('workspace_incomplete','工作区配置无法读取',12) from None
    from app.agent.methods import SKILLS
    files=[dist/'index.html',*[root/'.agents/skills'/('mathlens-'+s)/'SKILL.md' for s in SKILLS],
           *[root/'docs'/s for s in ('agent-workflow.md','question-sources.md','bank-source-interface.md')],
           Path(__file__).resolve().parents[1]/'agent/runtime_agents.md']
    if not root.is_dir() or any(not p.is_file() for p in files):raise DesktopError('resource_missing','安装资源不完整，请重新安装',2)
    # Actually read to catch permission failures before a task is created.
    for path in files:
        with path.open('rb') as stream:stream.read(1)
    return AppConfig(root,data,dist,data/name,False,library)
