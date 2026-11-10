"""Profile assignments reuse student submission URLs, with their own source."""
from typing import Literal
from fastapi import APIRouter,Depends,Request
from starlette.responses import JSONResponse,FileResponse
from app.api.dependencies import runtime
from app.api.schemas import RequestModel,Confirmation
from app.api.conditional import conditional

router=APIRouter(prefix='/api/practices',tags=['profile-practice'])

class Scope(RequestModel):
    subject:str|None=None
    chapter_topic_id:str|None=None

class Batch(Confirmation):
    request_id:str
    size:Literal[5,8,10]
    scope:Scope|None=None

@router.post('/profile-batch')
def create(body:Batch,rt=Depends(runtime)):
    value=rt.mutate(rt.profile_practice.create,body.model_dump(exclude_none=True))
    return JSONResponse(value,status_code=200 if value['reused'] else 202)

@router.get('/profile-batches/{batch_id}')
def batch(batch_id:str,request:Request,rt=Depends(runtime)):
    return conditional(request,rt.profile_practice.batch(batch_id))

@router.get('/{practice_id}/materials/{role}')
def image(practice_id:str,role:Literal['question','analysis','answer'],rt=Depends(runtime)):
    return FileResponse(rt.profile_practice.image(practice_id,role),headers={'Cache-Control':'no-store'})
