from fastapi import APIRouter,Depends,Body
from app.api.dependencies import runtime
router=APIRouter(prefix='/api',tags=['maintenance'])
@router.get('/data/status')
def data_status(rt=Depends(runtime)):
    from app.storage.path_upgrade import status
    return status(rt.config)
@router.get('/maintenance/backups')
def backups(rt=Depends(runtime)):return rt.local.backups()
@router.post('/maintenance/backup')
def backup(rt=Depends(runtime)):return rt.mutate(rt.local.backup)
@router.post('/maintenance/cleanup')
def cleanup(rt=Depends(runtime)):return rt.mutate(rt.local.cleanup)
@router.post('/maintenance/restore')
def restore(body:dict=Body(...),rt=Depends(runtime)):return rt.mutate(rt.local.restore,body.get('name',''),body.get('library_dir'),body.get('confirm_older_library',False))
@router.get('/mobile-upload/state')
def mobile_state(rt=Depends(runtime)):return rt.mobile_state()
@router.post('/mobile-upload/start')
def mobile_start(body:dict=Body(...),rt=Depends(runtime)):return rt.mutate(rt.mobile_start,body)
@router.post('/mobile-upload/stop')
def mobile_stop(rt=Depends(runtime)):return rt.mobile_stop()
