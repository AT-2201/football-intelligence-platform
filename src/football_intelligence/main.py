from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from football_intelligence import __version__
from football_intelligence.api.analytics_routes import router as analytics_router
from football_intelligence.api.routes import router
from football_intelligence.config import get_settings
from football_intelligence.db import create_tables


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Analytics foundation for Premier League 2015/16 StatsBomb Open Data.",
    lifespan=lifespan,
)
app.include_router(router)
app.include_router(analytics_router)

static_dir = Path(__file__).parent / "static"
app.mount("/assets", StaticFiles(directory=static_dir), name="assets")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
