from typing import Literal
from fastapi import APIRouter,Depends
from app.api.schemas import Confirmation
from app.api.dependencies import runtime
from app.services.paper_metadata import PaperMetadata
from pydantic import Field
router=APIRouter(prefix='/api/papers',tags=['paper-metadata'])
class Dates(Confirmation):
    request_id:str
    paper_ids:list[str]=Field(min_length=1,max_length=50)
    exam_date:str|None=None
    exam_date_precision:Literal['day','month','unknown']|None=None
    exam_date_unknown_reason:Literal['not_provided','forgotten']|None=None
class Decision(Confirmation):
    request_id:str
    decision:Literal['retake','withdraw']
    decision_revision:str
@router.post('/dates')
def dates(body:Dates,rt=Depends(runtime)):
    return rt.mutate(PaperMetadata(rt.config,rt.database).dates,body.model_dump())
@router.post('/{paper_id}/import-decision')
def decision(paper_id:str,body:Decision,rt=Depends(runtime)):
    return rt.mutate(PaperMetadata(rt.config,rt.database).decision,paper_id,body.model_dump())
