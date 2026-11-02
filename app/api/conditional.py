"""Conditional responses for the new JSON read resources only."""
import hashlib
from starlette.responses import JSONResponse, Response


def conditional(request, value):
    response = JSONResponse(value)
    tag = '"'+hashlib.sha256(response.body).hexdigest()+'"'
    headers = {'ETag': tag, 'Cache-Control': 'private, no-cache'}
    supplied = request.headers.get('if-none-match', '')
    if any(t.strip().removeprefix('W/') in (tag, '*') for t in supplied.split(',')):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return response
