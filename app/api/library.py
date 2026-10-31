from fastapi import APIRouter,Depends,Body,Query
from app.api.dependencies import runtime
from app.api.schemas import Reveal,BankNavigationCorrection,BankIdentityPreview,BankIdentityReview
from app.api.responses import resource_response
router=APIRouter(prefix='/api/bank',tags=['library'])
@router.get('')
def browse(math_type:str='',year:str='',rt=Depends(runtime)):return rt.library.browse(math_type,year)
@router.get('/search')
def search(topic_id:list[str]=Query(...),stage:list[str]|None=Query(None),method:list[str]|None=Query(None),
           offset:int=0,limit:int=30,include_history:bool=False,rt=Depends(runtime)):
    return rt.library.search(topic_ids=topic_id,stages=stage,methods=method,offset=offset,
                             limit=limit,include_history=include_history)
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
@router.get('/{bank_id}/{role}')
def bank_resource(bank_id:str,role:str,view:str='probe',probe_id:str|None=None,rt=Depends(runtime)):
    return resource_response(rt.resources.bank(bank_id,role,view=='library',probe_id))
