"""FastAPI application entry point."""

from fastapi import FastAPI
from app.api.decode import router as decode_router
from app.api.homework import router as homework_router

app = FastAPI(
    title="PoE2LI - PoE2 Intelligent Tool Site",
    description="Backend API for decoding PoB codes and generating build guides",
    version="0.1.0",
)

app.include_router(decode_router)
app.include_router(homework_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
