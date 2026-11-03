from fastapi import APIRouter,Depends,UploadFile,File,Form,Body,Request,Query
from app.api.conditional import conditional
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from app.api.dependencies import runtime
from app.api.schemas import Confirmation,Score,PaperDraft,Numbers,QuestionReview
from app.api.responses import resource_response
from app.api.schemas import PreparePractice,CorrectQuestions
router=APIRouter(prefix='/api',tags=['papers'])
@router.post('/papers/{paper_id}/prepare-practice',status_code=201)
def prepare_practice(paper_id:str,body:PreparePractice,rt=Depends(runtime)):
    from app.errors import ServiceError
    with rt.database.session() as conn:
        paper=conn.execute('SELECT archived_at FROM papers WHERE id=?',(paper_id,)).fetchone()
        if not paper:raise ServiceError('试卷不存在',404)
        if paper[0]:raise ServiceError('请先恢复已归档试卷',409)
    rt.agent.invoke('task',{'kind':'prepare_practice','paper_id':paper_id,'request_id':body.request_id})
    rt.wake()
    return rt.tasks.read()

@router.post('/papers/{paper_id}/questions/correct')
def correct_questions(paper_id:str,body:CorrectQuestions,rt=Depends(runtime)):
    return rt.mutate(rt.papers.correct_questions,paper_id,body.model_dump())
@router.get('/papers')
def papers(request:Request,archived:str='0',offset:int|None=Query(None,ge=0),limit:int|None=Query(None,ge=1,le=100),rt=Depends(runtime)):
    if offset is None and limit is None:return rt.workspace.papers(archived)
    return conditional(request,rt.frontend.papers(archived,offset or 0,limit or 20))
@router.post('/papers',status_code=201)
def create_paper(body:PaperDraft,rt=Depends(runtime)):return rt.mutate(rt.papers.create,body.model_dump())
@router.post('/papers/import')
async def import_paper(file:UploadFile=File(...),title:str=Form(''),exam_date:str=Form(''),rt=Depends(runtime)):
    content=await file.read(80*1024*1024+1)
    result,status=await run_in_threadpool(rt.mutate,rt.papers.import_pdf,file.filename,content,{'title':title,'exam_date':exam_date})
    return JSONResponse(result,status_code=status)
@router.get('/papers/{paper_id}/file')
def paper_file(paper_id:str,rt=Depends(runtime)):return resource_response(rt.resources.paper(paper_id))
@router.post('/papers/{paper_id}/analyze',status_code=201)
def analyze(paper_id:str,body:Confirmation=Body(default_factory=Confirmation),rt=Depends(runtime)):return rt.mutate(rt.papers.analyze_and_queue,paper_id,body.confirmed)
@router.post('/papers/{paper_id}/archive')
def archive(paper_id:str,body:Confirmation,rt=Depends(runtime)):return rt.mutate(rt.papers.archive,paper_id,True,body.confirmed)
@router.post('/papers/{paper_id}/restore')
def restore(paper_id:str,body:Confirmation,rt=Depends(runtime)):return rt.mutate(rt.papers.archive,paper_id,False,body.confirmed)
@router.post('/papers/{paper_id}/score')
def score(paper_id:str,body:Score,rt=Depends(runtime)):return rt.mutate(rt.papers.score,paper_id,body.model_dump())
@router.post('/papers/{paper_id}/confirm',status_code=201)
def confirm(paper_id:str,body:Numbers,rt=Depends(runtime)):return rt.mutate(rt.papers.confirm_numbers,paper_id,body.model_dump())
@router.post('/papers/{paper_id}/resummarize',status_code=201)
def summarize(paper_id:str,body:Confirmation,rt=Depends(runtime)):return rt.mutate(rt.agent.summarize,paper_id,body.confirmed)
@router.get('/questions/{question_id}/evidence')
def evidence(question_id:str,region:int=0,rt=Depends(runtime)):return resource_response(rt.resources.evidence(question_id,region))
@router.post('/questions/{question_id}/review',status_code=201)
def review(question_id:str,body:QuestionReview,rt=Depends(runtime)):return rt.mutate(rt.practice.review_question,question_id,body.model_dump())
