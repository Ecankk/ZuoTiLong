from fastapi import APIRouter,Depends,Body
from app.api.dependencies import runtime
from app.api.schemas import PracticeTask
router=APIRouter(prefix='/api/agent',tags=['agent'])
@router.get('/models')
def models(rt=Depends(runtime)):
    if rt.bridge is None:return {'status':'unavailable','reason':'disabled','message':'学习服务未启用','items':[]}
    return rt.bridge.models()
@router.get('/state')
def state(rt=Depends(runtime)):return rt.agent.snapshot()
@router.post('/task')
def task(body:PracticeTask,rt=Depends(runtime)):
    rt.agent.invoke('task',body.model_dump())
    return rt.agent.snapshot()
@router.post('/{action}')
def action(action:str,body:dict=Body(default_factory=dict),rt=Depends(runtime)):
    rt.agent.invoke(action,body)
    return rt.agent.snapshot()
