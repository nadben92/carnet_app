"""Modèles Pydantic v2 - validation et sérialisation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Réponse du endpoint /health."""

    model_config = ConfigDict(from_attributes=True)

    status: str
    database: str
    timestamp: datetime
