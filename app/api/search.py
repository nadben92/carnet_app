"""Recherche sémantique de vêtements."""

from fastapi import APIRouter, Depends, HTTPException, Query
from mistralai.client import Mistral
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.mistral_api_errors import mistral_exception_to_user_response
from app.core.mistral_trace import MistralCallTimeoutError, traced_mistral_call
from app.database import get_db
from app.models.garment import Garment

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=list[dict])
async def semantic_search(
    q: str = Query(..., min_length=1, description="Requête de recherche textuelle"),
    limit: int = Query(8, ge=1, le=20, description="Nombre de résultats à retourner"),
    gender: str | None = Query(None, description="Filtre genre: homme, femme, unisex"),
    price_min: float | None = Query(None, ge=0, description="Prix minimum (€)"),
    price_max: float | None = Query(None, ge=0, description="Prix maximum (€)"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """
    Recherche sémantique : trouve les vêtements les plus proches de la requête textuelle.
    Utilise Mistral Embed pour vectoriser la requête et pgvector pour la similarité cosinus.
    """
    settings = get_settings()

    if not settings.mistral_api_key:
        raise HTTPException(
            status_code=503,
            detail="MISTRAL_API_KEY non configurée. Impossible d'effectuer la recherche.",
        )

    # 1. Générer l'embedding de la requête via Mistral
    try:
        async with Mistral(api_key=settings.mistral_api_key) as client:
            res = await traced_mistral_call(
                "embeddings.create.search",
                client.embeddings.create_async(
                    model=settings.mistral_embed_model,
                    inputs=[q],
                ),
            )
        query_embedding = res.data[0].embedding
    except MistralCallTimeoutError:
        raise HTTPException(
            status_code=504,
            detail="L'API Mistral (embeddings) a mis trop longtemps à répondre.",
        ) from None
    except Exception as e:
        mapped = mistral_exception_to_user_response(e)
        if mapped:
            raise HTTPException(status_code=mapped[0], detail=mapped[1]) from e
        raise HTTPException(
            status_code=503,
            detail=f"Erreur API Mistral : {str(e)}",
        ) from e

    # 2. Requête SQLAlchemy avec cosine_distance + filtres
    distance_col = Garment.embedding.cosine_distance(query_embedding)
    conditions = [Garment.embedding.isnot(None)]
    if gender and gender.lower() in ("homme", "femme", "unisex"):
        conditions.append(Garment.gender == gender.lower())
    if price_min is not None:
        conditions.append(Garment.price >= price_min)
    if price_max is not None:
        conditions.append(Garment.price <= price_max)

    stmt = (
        select(Garment, distance_col.label("distance"))
        .where(and_(*conditions))
        .order_by(distance_col)
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    # 3. Formater la réponse
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


@router.get("/garment", response_model=dict | None)
async def get_garment_by_name(
    name: str = Query(..., description="Nom exact du vêtement"),
    db: AsyncSession = Depends(get_db),
) -> dict | None:
    """Récupère un vêtement par son nom exact (avec size_guide)."""
    result = await db.execute(select(Garment).where(Garment.name == name))
    garment = result.scalar_one_or_none()
    if not garment:
        return None
    return {
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
    }
