"""API registration order; SPA fallback is registered after this router."""

from fastapi import APIRouter

from app.api import agent, knowledge, library, maintenance, papers, practice, question_index, workspace, frontend_resources

router = APIRouter()
for routes in (workspace, papers, practice, library, agent, maintenance, knowledge, question_index, frontend_resources):
    router.include_router(routes.router)
