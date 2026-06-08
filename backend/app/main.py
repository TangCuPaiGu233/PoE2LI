"""FastAPI application entry point."""

import logging

# Configure root logger so logger.info() calls in services are visible
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.decode import router as decode_router
from app.api.homework import router as homework_router
from app.api.builds import router as builds_router
from app.api.knowledge import router as knowledge_router
from app.api.trade import router as trade_router


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

# CORS — allow frontend to call API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(decode_router)
app.include_router(homework_router)
app.include_router(builds_router)
app.include_router(knowledge_router)
app.include_router(trade_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
