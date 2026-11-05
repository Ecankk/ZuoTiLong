from fastapi import APIRouter,Depends,Body,Query,Request
from fastapi.responses import FileResponse
from app.api.conditional import conditional
from app.api.dependencies import runtime
from app.api.schemas import FreeAttempt,Reveal,BankNavigationCorrection,BankIdentityPreview,BankIdentityReview
from app.api.responses import resource_response
router=APIRouter(prefix='/api/bank',tags=['library'])
@router.get('')
def browse(request:Request,math_type:str='',year:str='',topic_id:str|None=None,collection:str|None=None,q:str='',offset:int|None=Query(None,ge=0),limit:int|None=Query(None,ge=1,le=100),rt=Depends(runtime)):
    if not q and offset is None and limit is None and topic_id is None and collection is None:return rt.library.browse(math_type,year)
    return conditional(request,rt.frontend.bank(math_type,year,topic_id,offset or 0,limit or 20,collection,q))
@router.get('/collections')
def collections(request:Request,rt=Depends(runtime)):
    return conditional(request,rt.frontend.collections())
@router.get('/search')
def search(topic_id:list[str]=Query(...),stage:list[str]|None=Query(None),method:list[str]|None=Query(None),collection:str|None=None,
           offset:int=0,limit:int=30,include_history:bool=False,rt=Depends(runtime)):
    return rt.library.search(topic_ids=topic_id,stages=stage,methods=method,offset=offset,
                             limit=limit,include_history=include_history,collection=collection)
@router.post('/import',status_code=201)
def import_text(body:dict|list=Body(...),rt=Depends(runtime)):return rt.mutate(rt.library.import_text,body)
@router.get('/topics')
def bank_topics(bank_id:list[str]=Query(...),rt=Depends(runtime)):
    return rt.knowledge_links.topics(bank_id)
@router.get('/{bank_id}/topics')
def question_topics(bank_id:str,rt=Depends(runtime)):
    return rt.knowledge_links.topics([bank_id])
@router.post('/identity-reviews/preview')
def preview_identity(body:BankIdentityPreview,rt=Depends(runtime)):
    return rt.library.preview_identity(body.model_dump())
@router.post('/identity-reviews')
def review_identity(body:BankIdentityReview,rt=Depends(runtime)):
    return rt.mutate(rt.library.review_identity,body.model_dump())
@router.post('/{bank_id}/reveal')
def reveal(bank_id:str,body:Reveal,rt=Depends(runtime)):return rt.library.reveal(bank_id,body.role,body.confirmed)
@router.post('/{bank_id}/navigation')
def correct_navigation(bank_id:str,body:BankNavigationCorrection,rt=Depends(runtime)):
    return rt.mutate(rt.library.correct_navigation,bank_id,body.model_dump())
@router.get('/{bank_id}/practice')
def free_practice(bank_id:str,rt=Depends(runtime)):
    return rt.free_practice.view(bank_id)
@router.get('/{bank_id}/practice/attempts')
def free_history(bank_id:str,offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=100),rt=Depends(runtime)):
    return rt.free_practice.history(bank_id,offset,limit)
@router.post('/{bank_id}/practice/attempts')
def free_submit(bank_id:str,body:FreeAttempt,rt=Depends(runtime)):
    return rt.mutate(rt.free_practice.submit,bank_id,body.model_dump())
@router.get('/{bank_id}/practice/attempts/{attempt_id}/materials/{role}')
def free_image(bank_id:str,attempt_id:str,role:str,rt=Depends(runtime)):
    return FileResponse(rt.free_practice.image(bank_id,attempt_id,role))
@router.get('/{bank_id}/{role}')
def bank_resource(bank_id:str,role:str,view:str='probe',probe_id:str|None=None,rt=Depends(runtime)):
    return resource_response(rt.resources.bank(bank_id,role,view=='library',probe_id))
