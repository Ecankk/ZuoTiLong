"""Translate application failures at the HTTP boundary."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.agent.errors import BridgeConflict


async def conflict(request: Request, exc: BridgeConflict):
    return JSONResponse({'error': str(exc)}, status_code=409)


async def invalid(request: Request, exc: Exception):
    return JSONResponse({'error': str(exc)}, status_code=getattr(exc, 'status', 400))


async def validation(request: Request, exc: RequestValidationError):
    error = exc.errors()[0]
    field = '.'.join(str(key) for key in error['loc'] if key != 'body')
    return JSONResponse({'error': f"{field or '请求'}: {error['msg']}"}, status_code=400)


async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({'error': str(exc.detail)}, status_code=exc.status_code)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(BridgeConflict, conflict)
    for error_type in (ValueError, RuntimeError, TimeoutError):
        app.add_exception_handler(error_type, invalid)
    app.add_exception_handler(RequestValidationError, validation)
    app.add_exception_handler(HTTPException, http_error)
