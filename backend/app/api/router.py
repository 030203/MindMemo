from fastapi import APIRouter

from app.api.v1 import admin, auth, chat, dashboard, ingest, insights, memories, qa, review_queue, settings, timeline, todos, trajectory

api_router = APIRouter()
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(memories.router, prefix="/memories", tags=["memories"])
api_router.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
api_router.include_router(todos.router, prefix="/todos", tags=["todos"])
api_router.include_router(timeline.router, prefix="/timeline", tags=["timeline"])
api_router.include_router(insights.router, prefix="/insights", tags=["insights"])
api_router.include_router(qa.router, prefix="/qa", tags=["qa"])
api_router.include_router(review_queue.router, prefix="/review-queue", tags=["review-queue"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(trajectory.router, prefix="/trajectory", tags=["trajectory"])
