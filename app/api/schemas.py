"""HTTP request models; Agent result contracts remain independently versioned."""
from typing import Any,Literal
from pydantic import BaseModel,ConfigDict,Field,StrictBool,StrictFloat,StrictInt

class RequestModel(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Confirmation(RequestModel):confirmed:StrictBool=False
class KnowledgeOrganize(RequestModel):
    source_ids:list[str]|None=None
    refresh:StrictBool=False
    request_id:str|None=None
class Score(Confirmation):
    score:StrictFloat|StrictInt
    total_score:StrictFloat|StrictInt=150
    math_type:StrictInt=Field(ge=1,le=3)
class PaperDraft(RequestModel):
    title:str=''
    exam_date:str|None=None
    score:float=0
    total_score:float=150
    duration:int=0
    source_name:str|None=None
class Numbers(RequestModel):
    numbers:list[str|int]=Field(default_factory=list)
    scores:list[float|str]=Field(default_factory=list)
    subject:str='数学一'
class Attempt(RequestModel):
    response:str=''
    image_ids:list[str]=Field(default_factory=list)
    image_roles:dict[str,str]=Field(default_factory=dict)
    answer_exposed:StrictBool=False
    request_id:str|None=None
    elapsed_seconds:float|None=None
class QuestionReview(RequestModel):
    request_id:str
    report_id:str
    note:str=''
    image_ids:list[str]=Field(default_factory=list)
    image_roles:dict[str,str]=Field(default_factory=dict)
class PracticeTask(RequestModel):
    kind:Literal['analyze_paper','review_question','prepare_practice','grade_attempt','summarize_paper','organize_knowledge','maintain_catalog','annotate_questions','review_practice']
    paper_id:str|None=None
    request_id:str
    attempt_id:str|None=None
    review_request:dict[str,Any]|None=None
    task_scope:dict[str,Any]|None=None
class Reveal(Confirmation):role:Literal['question','analysis','answer']='question'
class BankNavigationCorrection(Confirmation):
    request_id:str
    expected_material_revision:str=Field(pattern=r'^[0-9a-f]{64}$')
    topic:str=Field(min_length=1,max_length=160)
    reason:str=Field(min_length=8,max_length=1500)
class BankIdentityPreview(RequestModel):
    left_id:str=Field(min_length=1,max_length=180)
    right_id:str=Field(min_length=1,max_length=180)
    operation:Literal['confirm','revoke']
class BankIdentityReview(BankIdentityPreview,Confirmation):
    request_id:str
    expected_preview_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    reason:str=Field(min_length=8,max_length=1500)
class CandidateImport(RequestModel):directory:str
class KnowledgePreparation(RequestModel):
    kind:Literal['catalog','questions']
    request_id:str
    source_version_id:str|None=None
    item_ids:list[str]|None=Field(default=None,max_length=10000)
    auto_annotate:StrictBool=False
    batch_size:StrictInt|None=None
class PreparationAction(RequestModel):operation:Literal['pause','resume']
class CatalogPackagePreview(RequestModel):package:dict[str,Any]
class CatalogPackageImport(Confirmation):
    package:dict[str,Any]
    trusted_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    expected_active_release_id:str|None
class CatalogPackageActivation(Confirmation):
    sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    expected_active_release_id:str
class QuestionIndexPreview(RequestModel):package:dict[str,Any]
class QuestionIndexImport(Confirmation):
    package:dict[str,Any]
    trusted_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    expected_preview_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
class QuestionIndexState(Confirmation):
    sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    enabled:StrictBool
class Draft(RequestModel):
    key:str=Field(max_length=300)
    value:Any=None
class Prompt(RequestModel):prompt:str=Field(max_length=1000)
class Preferences(RequestModel):
    study_type:StrictInt=Field(ge=1,le=3)
    mask_same_type:StrictBool=True
    reserved:list[dict[str,Any]]=Field(default_factory=list)
    paper_marking_convention:str|None=None
