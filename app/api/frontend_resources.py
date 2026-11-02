"""Resource reads for the new frontend; legacy routes remain registered."""
from fastapi import APIRouter, Depends, Request, Query
from app.api.dependencies import runtime
from app.api.conditional import conditional

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
              topic_id: str|None=None, include_inactive: bool=False,
              offset: int=Query(0, ge=0), limit: int=Query(20, ge=1, le=100), rt=Depends(runtime)):
    return conditional(request, rt.frontend.practices(group_by, status, paper_id, topic_id, include_inactive, offset, limit))


@router.get('/practices/{practice_id}')
def practice(practice_id: str, request: Request, rt=Depends(runtime)):
    return conditional(request, rt.frontend.practice(practice_id))


@router.get('/practices/{practice_id}/attempts')
def attempts(practice_id: str, request: Request, offset: int=Query(0, ge=0), limit: int=Query(20, ge=1, le=100), rt=Depends(runtime)):
    return conditional(request, rt.frontend.attempts(practice_id, offset, limit))


@router.get('/knowledge/topics/{topic_id}')
def topic(topic_id: str, request: Request, rt=Depends(runtime)):
    return conditional(request, rt.frontend.topic(topic_id))
