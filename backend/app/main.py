from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.services.bootstrap import initialize_database, initialize_tools
from app.services.reminder_scheduler import reminder_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    initialize_tools()
    await reminder_scheduler.start()
    try:
        yield
    finally:
        await reminder_scheduler.stop()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="MindMemo backend",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_origin,
        "http://localhost:6100",
        "http://127.0.0.1:6100",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

upload_root = Path(settings.upload_root).resolve()
upload_root.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=upload_root), name="uploads")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router, prefix=settings.api_prefix)
