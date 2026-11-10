from fastapi import APIRouter,Depends,Request,Query
from typing import Literal
from app.api.dependencies import runtime
from app.api.conditional import conditional
from app.api.schemas import RequestModel
router=APIRouter(prefix='/api',tags=['profile'])

@router.get('/profile/overview')
def overview(request:Request,rt=Depends(runtime)):return conditional(request,rt.profile.overview())

@router.get('/profile/trends')
def trends(request:Request,weeks:int=Query(12,ge=1,le=52),rt=Depends(runtime)):return conditional(request,rt.profile.trends(weeks))

@router.get('/profile/nodes/{node_id}/atoms')
def atoms(node_id:str,request:Request,offset:int=Query(0,ge=0),limit:int=Query(60,ge=1,le=100),rt=Depends(runtime)):
    return conditional(request,rt.profile.atoms(node_id,offset,limit))

class FeedbackRead(RequestModel):
    request_id:str
    source:Literal['paper_practice','profile_practice','free_practice']
    attempt_id:str
    feedback_revision:str

@router.post('/feedback/read')
def read_feedback(body:FeedbackRead,rt=Depends(runtime)):
    from app.learning.feedback import mark
    with rt.write_guard(),rt.database.session(write=True) as conn:return mark(conn,body.model_dump())
