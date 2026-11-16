# Windows x64, console-enabled onedir: stdio is the desktop protocol.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files,collect_dynamic_libs,copy_metadata
import json

project=Path(SPECPATH).resolve().parents[1]
datas=[(str(project/'app/agent/runtime_agents.md'),'app/agent')]
binaries=[]
for package in ('rapidocr_onnxruntime','jsonschema_specifications'):
    datas+=collect_data_files(package)
for package in ('onnxruntime','cv2','numpy','shapely','pyclipper','pymupdf','PIL'):
    binaries+=collect_dynamic_libs(package)
for wheel in json.loads((Path(SPECPATH)/'wheels-win-x64-py312.json').read_text(encoding='utf8'))['wheels']:
    datas+=copy_metadata(wheel['name'])
hidden=['uvicorn.logging','uvicorn.loops.asyncio','uvicorn.protocols.http.h11_impl','uvicorn.lifespan.on',
        'rapidocr_onnxruntime','onnxruntime.capi.onnxruntime_pybind11_state','pymupdf',
        'PIL.JpegImagePlugin','PIL.PngImagePlugin','PIL.WebPImagePlugin']
a=Analysis([str(project/'scripts/packaging/backend_entry.py')],pathex=[str(project)],
           binaries=binaries,datas=datas,hiddenimports=hidden,hookspath=[],runtime_hooks=[],
           excludes=['tkinter','pytest','httpx','unittest','IPython','matplotlib'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='mathlens-backend',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=True,contents_directory='_internal')
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='mathlens-backend')
