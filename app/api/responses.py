"""HTTP conversion of application-owned resources."""
from fastapi.responses import FileResponse, Response
from pathlib import Path

SAFE_TYPES={'image/png','image/jpeg','image/webp','image/gif','application/pdf','application/json'}
FILE_TYPES={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.gif':'image/gif','.pdf':'application/pdf','.json':'application/json'}


def file_response(path,headers=None):
    path=Path(path)
    return _response(path,FILE_TYPES.get(path.suffix.lower(),'application/octet-stream'),headers)


def _response(content,media_type,headers=None):
    safe=media_type in SAFE_TYPES
    media_type=media_type if safe else 'application/octet-stream'
    headers={**(headers or {}),'X-Content-Type-Options':'nosniff'}
    if not safe:headers['Content-Disposition']='attachment'
    if isinstance(content,bytes):return Response(content,media_type=media_type,headers=headers)
    return FileResponse(content,media_type=media_type,headers=headers)


def resource_response(value):
    return _response(value.content,value.media_type)
