"""Logique de recherche vectorielle partagée (RAG)."""

from mistralai.client import Mistral
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.mistral_trace import traced_mistral_call
from app.models.garment import Garment


async def get_relevant_garments(
    db: AsyncSession,
    query: str,
    api_key: str,
    limit: int = 8,
    price_min: float | None = None,
    price_max: float | None = None,
    gender: str | None = None,
) -> list[dict]:
    """
    Retourne les vêtements les plus pertinents pour une requête textuelle.
    Combine recherche sémantique (embeddings Mistral) avec filtres genre et prix.
    """
    embed_model = get_settings().mistral_embed_model
    async with Mistral(api_key=api_key) as client:
        res = await traced_mistral_call(
            "embeddings.create.rag",
            client.embeddings.create_async(
                model=embed_model,
                inputs=[query],
            ),
        )
    query_embedding = res.data[0].embedding

    distance_col = Garment.embedding.cosine_distance(query_embedding)
    conditions = [Garment.embedding.isnot(None)]
    if price_min is not None:
        conditions.append(Garment.price >= price_min)
    if price_max is not None:
        conditions.append(Garment.price <= price_max)
    if gender and gender.lower() in ("homme", "femme", "unisex"):
        conditions.append(Garment.gender == gender.lower())

    stmt = (
        select(Garment, distance_col.label("distance"))
        .where(and_(*conditions))
        .order_by(distance_col)
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "id": garment.id,
            "name": garment.name,
            "brand": garment.brand,
            "category": garment.category,
            "gender": garment.gender,
            "description": garment.description or "",
            "price": garment.price,
            "stock": garment.stock,
            "image_url": garment.image_url,
            "size_guide": garment.size_guide,
            "distance": round(float(distance), 6),
        }
        for garment, distance in rows
    ]
