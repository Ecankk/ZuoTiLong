"""Upload and confirm a data-only collection pack, with no personal DB writes."""
import hashlib,re,tempfile,uuid,zipfile
from pathlib import Path
from fastapi import APIRouter,Depends,UploadFile,File,Body
from starlette.concurrency import run_in_threadpool
from app.api.dependencies import runtime
from app.errors import ServiceError
from app.bank.collection_packs import import_collection,PackTooLarge

router=APIRouter(prefix='/api/library/collection-packs',tags=['collection-packs'])

def cache():
    path=Path(tempfile.gettempdir())/'mathlens-collection-packs';path.mkdir(exist_ok=True)
    return path

def run(rt,path,confirm=None):
    try:return import_collection(rt.config,path,confirm)
    except PackTooLarge as exc:raise ServiceError(str(exc),413) from exc
    except (zipfile.BadZipFile,KeyError,TypeError,AttributeError) as exc:raise ServiceError('题集包格式不合法：'+str(exc)[:200],400) from exc
    except ValueError as exc:
        status=409 if any(s in str(exc) for s in ('过期','变化','冲突','正在','未完成')) else 400
        raise ServiceError(str(exc),status) from exc

@router.post('/preview')
async def preview(file:UploadFile=File(...),rt=Depends(runtime)):
    temporary=cache()/(uuid.uuid4().hex+'.upload');sha=hashlib.sha256();size=0
    try:
        with temporary.open('wb') as output:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>1024**3:raise ServiceError('题集包超过1GiB',413)
                sha.update(chunk);output.write(chunk)
        target=cache()/(sha.hexdigest()+'.zip')
        if not target.exists():temporary.replace(target)
        return await run_in_threadpool(run,rt,target)
    finally:temporary.unlink(missing_ok=True);await file.close()

@router.post('/confirm')
def confirm(body:dict=Body(...),rt=Depends(runtime)):
    if body.get('confirmed') is not True:raise ValueError('请明确确认接受题集包来源')
    sha=body.get('package_sha256','');plan=body.get('plan_sha256','')
    if not isinstance(sha,str) or not isinstance(plan,str) or not re.fullmatch('[0-9a-f]{64}',sha) or not re.fullmatch('[0-9a-f]{64}',plan):raise ValueError('包/预演摘要无效')
    path=cache()/(sha+'.zip')
    if not path.is_file():raise ServiceError('暂存题集包不存在，请重新上传预演',404)
    bridge=rt.bridge
    if bridge:
        with bridge.lock:
            bridge.assert_user_write_allowed();bridge.preparing=True
    try:return run(rt,path,plan)
    finally:
        if bridge:
            with bridge.lock:bridge.preparing=False
        rt.wake()
