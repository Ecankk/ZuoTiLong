"""Resource reads for the new frontend; legacy routes remain registered."""
from fastapi import APIRouter, Depends, Request, Query
from app.api.dependencies import runtime
from app.api.conditional import conditional
from app.api.schemas import RequestModel
from typing import Literal
from starlette.responses import StreamingResponse

router = APIRouter(prefix='/api', tags=['frontend-resources'])


@router.get('/papers/{paper_id}')
def paper(paper_id: str, request: Request, rt=Depends(runtime)):
    return conditional(request, rt.frontend.paper(paper_id))


@router.get('/papers/{paper_id}/questions')
def questions(paper_id: str, request: Request, rt=Depends(runtime)):
    return conditional(request, rt.frontend.questions(paper_id))


@router.get('/papers/{paper_id}/summary')
def summary(paper_id: str, request: Request, rt=Depends(runtime)):
    return conditional(request, rt.frontend.summary(paper_id))


@router.get('/questions/{question_id}')
def question(question_id: str, request: Request, rt=Depends(runtime)):
    return conditional(request, rt.frontend.question(question_id))


@router.get('/practices')
def practices(request: Request, group_by: str='topic', status: str|None=None, paper_id: str|None=None,
              topic_id: str|None=None, include_inactive: bool=False,source:str|None=None,batch_id:str|None=None,
              offset: int=Query(0, ge=0), limit: int=Query(20, ge=1, le=100), rt=Depends(runtime)):
    return conditional(request, rt.frontend.practices(group_by, status, paper_id, topic_id, include_inactive, offset, limit,source,batch_id))


@router.get('/practices/{practice_id}')
def practice(practice_id: str, request: Request, rt=Depends(runtime)):
    return conditional(request, rt.frontend.practice(practice_id))


@router.get('/practices/{practice_id}/attempts')
def attempts(practice_id: str, request: Request, offset: int=Query(0, ge=0), limit: int=Query(20, ge=1, le=100), rt=Depends(runtime)):
    return conditional(request, rt.frontend.attempts(practice_id, offset, limit))


@router.get('/knowledge/topics/{topic_id}')
def topic(topic_id: str, request: Request, rt=Depends(runtime)):
    return conditional(request, rt.frontend.topic(topic_id))


@router.get('/tasks')
def tasks(request: Request, status: str|None=None, offset: int=Query(0, ge=0), limit: int=Query(20, ge=1, le=100), rt=Depends(runtime)):
    return conditional(request, rt.tasks.read(status, offset, limit))


class TaskAction(RequestModel):
    action: Literal['retry', 'cancel']


@router.post('/tasks/{job_id}/action')
def task_action(job_id: str, body: TaskAction, rt=Depends(runtime)):
    return rt.tasks.action(job_id, body.action)


@router.get('/events')
async def events(request: Request, rt=Depends(runtime)):
    return StreamingResponse(rt.events.stream(request), media_type='text/event-stream',
                             headers={'Cache-Control':'no-store', 'X-Accel-Buffering':'no'})
