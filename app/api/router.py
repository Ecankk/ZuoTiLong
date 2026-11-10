"""API registration order; SPA fallback is registered after this router."""

from fastapi import APIRouter

from app.api import collection_packs,agent, knowledge, library, maintenance, papers, practice, question_index, workspace, frontend_resources,profile,profile_practice

router = APIRouter()
for routes in (collection_packs,workspace, papers, practice, library, agent, maintenance, knowledge, question_index, profile_practice,frontend_resources,profile):
    router.include_router(routes.router)
