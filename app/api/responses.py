"""HTTP conversion of application-owned resources."""
from fastapi.responses import FileResponse, Response


def resource_response(value):
    if isinstance(value.content, bytes):
        return Response(value.content, media_type=value.media_type)
    return FileResponse(value.content, media_type=value.media_type)
