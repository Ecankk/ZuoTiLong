"""Explicit shared-index import/export; never executes a learning task."""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from app.api.dependencies import runtime
from app.api.schemas import QuestionIndexPreview, QuestionIndexImport, QuestionIndexState

router = APIRouter(prefix='/api/knowledge/question-index', tags=['question-index'])


@router.get('')
def listing(rt=Depends(runtime)):
    return rt.question_index.listing()


@router.get('/export')
def export(collection:str|None=None,rt=Depends(runtime)):
    package = rt.question_index.export(collection)
    return JSONResponse(package, headers={'X-Content-Type-Options':'nosniff','Content-Disposition': 'attachment; filename="question-index-' + package['sha256'][:12] + '.json"'})


@router.post('/preview')
def preview(body: QuestionIndexPreview, rt=Depends(runtime)):
    return rt.question_index.preview(body.package,body.collection)


@router.post('/import')
def import_package(body: QuestionIndexImport, rt=Depends(runtime)):
    return rt.mutate(rt.question_index.import_package, body.model_dump())


@router.post('/state')
def set_enabled(body: QuestionIndexState, rt=Depends(runtime)):
    return rt.mutate(rt.question_index.set_enabled, body.model_dump())
