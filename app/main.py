"""Point d'entrée FastAPI - Personal Shopper asynchrone."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import router as auth_router
from app.api.cart import router as cart_router
from app.api.chat import router as chat_router
from app.api.profile import router as profile_router
from app.api.search import router as search_router
from app.api.size_extractor import router as size_extractor_router
from app.api.transcription import router as transcription_router
from app.database import get_db
from app.middleware.logging_middleware import RequestLoggingMiddleware
from app.schemas import HealthResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Personal Shopper API",
    description="Application asynchrone de Personal Shopper - Test technique Mistral AI",
    version="0.1.0",
)

app.add_middleware(RequestLoggingMiddleware)

app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(cart_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(size_extractor_router)
app.include_router(transcription_router)


@app.get("/", response_class=FileResponse)
async def index():
    """Interface utilisateur Personal Shopper."""
    path = Path(__file__).parent / "templates" / "index.html"
    return FileResponse(path, media_type="text/html")


@app.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """
    Vérifie l'état de l'application et teste la connexion à la base de données.
    """
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="healthy" if db_status == "ok" else "degraded",
        database=db_status,
        timestamp=datetime.now(timezone.utc),
    )
