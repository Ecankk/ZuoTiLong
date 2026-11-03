from fastapi import APIRouter, Depends
from app.api.dependencies import runtime
from app.api.schemas import (CandidateImport,KnowledgePreparation,PreparationAction,KnowledgeOrganize,
                             CatalogPackagePreview,CatalogPackageImport,CatalogPackageActivation)

router=APIRouter(prefix='/api/knowledge',tags=['knowledge'])


@router.get('/links/summary')
def link_summary(paper_id:str|None=None,rt=Depends(runtime)):
    return rt.knowledge_links.summary(paper_id)


@router.get('/links')
def question_links(view:str='bank',topic_id:str|None=None,scope:str='subtree',role:str|None=None,
                   status:str|None=None,math_type:int|None=None,year:str|None=None,
                   offset:int=0,limit:int=15,paper_id:str|None=None,catalog_revision:str|None=None,rt=Depends(runtime)):
    return rt.knowledge_links.links(view=view,topic_id=topic_id,scope=scope,role=role,status=status,
                                    math_type=math_type,year=year,offset=offset,limit=limit,paper_id=paper_id,
                                    expected_revision=catalog_revision)


@router.get('/packages')
def packages(rt=Depends(runtime)):
    return rt.knowledge_catalog.packages()


@router.get('/packages/export')
def export_package(rt=Depends(runtime)):
    from fastapi.responses import JSONResponse
    package = rt.knowledge_catalog.export_package()
    return JSONResponse(package, headers={'Content-Disposition': 'attachment; filename="catalog-'+package['sha256'][:12]+'.json"'})


@router.post('/packages/preview')
def preview_package(body:CatalogPackagePreview,rt=Depends(runtime)):
    return rt.knowledge_catalog.preview_package(body.package)


@router.post('/packages/import')
def import_package(body:CatalogPackageImport,rt=Depends(runtime)):
    return rt.mutate(rt.knowledge_catalog.import_package,body.model_dump())


@router.post('/packages/activate')
def activate_package(body:CatalogPackageActivation,rt=Depends(runtime)):
    return rt.mutate(rt.knowledge_catalog.activate_package,body.model_dump())


@router.get('')
def knowledge(rt=Depends(runtime)):
    return rt.knowledge.read()


@router.post('/organize')
def organize(body:KnowledgeOrganize|None=None,paper_id:str|None=None,rt=Depends(runtime)):
    return rt.mutate(rt.knowledge.organize,paper_id,body.model_dump(exclude_unset=True) if body else {})


@router.get('/catalog')
def catalog(query:str='',parent_id:str|None=None,kind:str|None=None,release_id:str|None=None,
            offset:int=0,limit:int=40,rt=Depends(runtime)):
    return rt.knowledge_catalog.search(query=query,parent_id=parent_id,kinds=[kind] if kind else None,
                                       release_id=release_id,offset=offset,limit=limit)


@router.get('/catalog/summary')
def catalog_summary(rt=Depends(runtime)):
    return rt.knowledge_catalog.summary()

@router.get('/catalog/tree')
def catalog_tree(rt=Depends(runtime)):
    return rt.knowledge_catalog.tree()


@router.get('/catalog/releases')
def catalog_releases(rt=Depends(runtime)):
    return rt.knowledge_catalog.releases()


@router.get('/catalog/releases/{release_id}')
def catalog_release(release_id:str,rt=Depends(runtime)):
    return rt.knowledge_catalog.release(release_id)


@router.get('/catalog/candidates')
def candidate_entries(source_version_id:str,chapter:str|None=None,kind:str='atom',query:str='',
                      offset:int=0,limit:int=40,rt=Depends(runtime)):
    return rt.knowledge_catalog.candidates(source_version_id=source_version_id,chapter=chapter,
                                           kind=kind,query=query,offset=offset,limit=limit)


@router.get('/preparation')
def preparation_status(rt=Depends(runtime)):
    return rt.knowledge_catalog.preparation()


@router.post('/preparation/import')
def import_candidates(body:CandidateImport,rt=Depends(runtime)):
    return rt.mutate(rt.knowledge_catalog.import_candidates,body.directory)


@router.post('/preparation/start')
def start_preparation(body:KnowledgePreparation,rt=Depends(runtime)):
    return rt.mutate(rt.knowledge_catalog.prepare,body.model_dump())


@router.post('/preparation/{run_id}/action')
def preparation_action(run_id:str,body:PreparationAction,rt=Depends(runtime)):
    # Scheduling controls may be requested during the current turn. They do
    # not alter its inputs or stop an unknown remote writer: pause waits for
    # its saved completion before dispatching another batch.
    if rt.bridge:
        with rt.bridge.lock:result=rt.knowledge_catalog.preparation_action(run_id,body.operation)
    else:result=rt.knowledge_catalog.preparation_action(run_id,body.operation)
    rt.wake();return result
