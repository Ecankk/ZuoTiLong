"""Request access to the services owned by this application instance."""

from fastapi import Request

from app.runtime import AppRuntime


def runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime
