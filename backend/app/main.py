"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.decode import router as decode_router
from app.api.homework import router as homework_router
from app.api.builds import router as builds_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup."""
    from app.core.database import engine, Base
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="PoE2LI - PoE2 Intelligent Tool Site",
    description="Backend API for decoding PoB codes and generating build guides",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(decode_router)
app.include_router(homework_router)
app.include_router(builds_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
