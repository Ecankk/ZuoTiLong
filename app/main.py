"""Application factory: assemble HTTP boundaries and own the service lifecycle."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.bridge import CodexBridge
from app.api.boundary import LocalBoundary
from app.api.errors import register_exception_handlers
from app.api.frontend import router as frontend_router
from app.api.router import router
from app.config import AppConfig
from app.runtime import AppRuntime
from app.version import VERSION


def create_app(
    config: AppConfig | None = None,
    *,
    bridge=None,
    agent_factory=CodexBridge,
    manage_agent: bool = True,
) -> FastAPI:
    runtime = AppRuntime(
        config or AppConfig.from_env(),
        bridge=bridge,
        agent_factory=agent_factory,
        manage_agent=manage_agent,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            runtime.start()
            yield
        finally:
            runtime.close()

    app = FastAPI(
        title='MathLens Local',
        version=VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.runtime = runtime
    app.add_middleware(LocalBoundary)
    register_exception_handlers(app)
    app.include_router(router)
    app.include_router(frontend_router)
    return app
