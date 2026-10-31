from fastapi import APIRouter,Depends,Body,File,UploadFile
from starlette.concurrency import run_in_threadpool
from app.api.dependencies import runtime
from app.api.schemas import Attempt
from app.api.responses import resource_response
router=APIRouter(prefix='/api',tags=['practice'])
@router.post('/probes/{probe_id}/submit',status_code=201)
def submit(probe_id:str,body:Attempt,rt=Depends(runtime)):return rt.mutate(rt.practice.submit,probe_id,body.model_dump(exclude_unset=True))
@router.post('/attempts/{attempt_id}/supplement')
def supplement(attempt_id:str,body:Attempt,rt=Depends(runtime)):return rt.mutate(rt.practice.supplement,attempt_id,body.model_dump(exclude_unset=True))
@router.post('/probes/{probe_id}/feedback')
def feedback(probe_id:str,body:dict=Body(...),rt=Depends(runtime)):return rt.mutate(rt.practice.feedback,probe_id,body.get('attempt_id'))
@router.get('/answer-images/{image_id}')
def answer_image(image_id:str,rt=Depends(runtime)):return resource_response(rt.resources.answer(image_id))
@router.post('/answer-images',status_code=201)
async def upload_images(files:list[UploadFile]=File(...),rt=Depends(runtime)):
    if not 1<=len(files)<=4:raise ValueError('请上传 1–4 张照片')
    contents=[await file.read(8*1024*1024+1) for file in files]
    return await run_in_threadpool(rt.mutate,rt.practice.upload_images,contents)
