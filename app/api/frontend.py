"""SPA files and unmatched routes, registered after the application API."""

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.dependencies import runtime
from app.runtime import AppRuntime

router = APIRouter(include_in_schema=False)


@router.post('/api/{path:path}')
def unknown_post(path: str):
    retired = (
        path.endswith(('/agent-report', '/revise', '/replace', '/diagnose'))
        or path == 'reviews'
        or path.startswith('reports/') and path.endswith('/restore')
    )
    if retired:
        raise ValueError('旧的学习结果直接写入入口已停用；请从对应试卷或作答启动任务，结果按任务契约保存')
    raise HTTPException(404, 'not found')


@router.get('/{path:path}')
def frontend(path: str, rt: AppRuntime = Depends(runtime)):
    if path.startswith('api/'):
        raise HTTPException(404, 'not found')
    dist = rt.config.dist
    candidate = (dist / (path or 'index.html')).resolve()
    if not candidate.is_relative_to(dist):
        raise HTTPException(404, 'not found')
    if not candidate.is_file():
        if Path(path).suffix:
            raise HTTPException(404, 'not found')
        candidate = dist / 'index.html'
    if not candidate.is_file():
        raise HTTPException(404, 'Frontend build unavailable')
    media_type = {
        '.html': 'text/html',
        '.css': 'text/css',
        '.js': 'application/javascript',
        '.json': 'application/json',
    }.get(candidate.suffix) or mimetypes.guess_type(candidate.name)[0]
    return FileResponse(candidate, media_type=media_type)
