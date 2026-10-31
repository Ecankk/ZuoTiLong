from fastapi import APIRouter,Depends,Body
from app.api.dependencies import runtime
from app.api.schemas import Draft,Preferences,Prompt
from app.hosting import data_identity
from app.version import VERSION
router=APIRouter(prefix='/api',tags=['workspace'])
@router.get('/health')
def health(rt=Depends(runtime)):return {'ok':True,'app':'mathlens','version':VERSION,'data_id':data_identity(rt.config.data)}
@router.get('/bootstrap')
def bootstrap(rt=Depends(runtime)):return rt.workspace.bootstrap()
@router.get('/loop')
def loop(rt=Depends(runtime)):return rt.workspace.loop()
@router.get('/profile')
def profile(rt=Depends(runtime)):return rt.workspace.profile()
@router.get('/preparation')
def preparation(rt=Depends(runtime)):return rt.local.preparation()
@router.get('/versions')
def versions(rt=Depends(runtime)):return rt.workspace.versions()
@router.get('/screen')
def screen(rt=Depends(runtime)):return rt.local.screen()
@router.post('/screen')
def save_screen(body:dict=Body(...),rt=Depends(runtime)):return rt.local.save_screen(body)
@router.get('/drafts')
def draft(key:str='',rt=Depends(runtime)):return rt.local.draft(key)
@router.post('/drafts')
def save_draft(body:Draft,rt=Depends(runtime)):return rt.local.save_draft(body.model_dump())
@router.get('/preferences')
def preferences(rt=Depends(runtime)):return rt.library.preferences()
@router.post('/preferences')
def save_preferences(body:Preferences,rt=Depends(runtime)):return rt.mutate(rt.library.save_preferences,body.model_dump(exclude_unset=True))
@router.post('/preferences/agent-prompt')
def save_prompt(body:Prompt,rt=Depends(runtime)):return rt.mutate(rt.library.save_prompt,body.model_dump())
