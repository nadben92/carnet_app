"""Chat RAG - Personal Shopper intelligent."""

from fastapi import APIRouter, Depends, Header, HTTPException
from mistralai.client import Mistral
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.mistral_api_errors import mistral_exception_to_user_response
from app.core.mistral_trace import MistralCallTimeoutError, traced_mistral_call
from app.database import get_db
from app.models.garment import Garment
from app.models.user import User
from app.models.user_profile import UserProfile
from app.services.auth import decode_access_token
from app.services.cart_merge import CartMergeError, merge_line_into_cart
from app.services.fit_advisor import get_fit_advisor_result
from app.services.retrieval import get_relevant_garments

router = APIRouter(prefix="/chat", tags=["chat"])

SYSTEM_PROMPT_BASE = """Tu es un conseiller mode : réponses COURTES (quelques phrases, pas de longues introductions ni pavés).

Règles :
- Recommande seulement des articles listés dans « Articles du catalogue » ci-dessous.
- Pour chaque article choisi, recopie son nom COMPLET EXACTEMENT comme dans la liste dans ton texte (sinon la fiche ne s’affichera pas côté client). Pas de version abrégée ni de reformulation du titre.
- Une ligne d’argument par article suffit (pourquoi ça colle à la demande).
- Pas de politesses répétées, pas de résumé de la question, pas de liste numérotée longue.
- Si le catalogue ne convient pas, dis-le en une phrase, sans citer d’article.

"""


class ChatRequest(BaseModel):
    """Corps de la requête POST /chat."""

    message: str = Field(..., min_length=1, description="Message de l'utilisateur")
    price_min: float | None = Field(None, ge=0, description="Prix minimum (€)")
    price_max: float | None = Field(None, ge=0, description="Prix maximum (€)")
    gender: str | None = Field(None, description="Filtre genre: homme, femme, unisex")


class ChatResponse(BaseModel):
    """Réponse du Personal Shopper."""

    reply: str = Field(..., description="Conseil de l'IA")
    sources: list[dict] = Field(..., description="Articles utilisés pour la réponse")


class SizeAdviceHistoryTurn(BaseModel):
    """Un tour de conversation précédent (sans le message courant)."""

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class SizeAdviceRequest(BaseModel):
    """Corps de la requête POST /chat/size-advice."""

    garment_name: str = Field(..., min_length=1)
    garment_id: int | None = Field(
        None,
        ge=1,
        description="Identifiant catalogue (recommandé pour l’ajout panier automatique)",
    )
    size_guide: dict | None = Field(None, description="Guide des tailles du vêtement")
    message: str | None = Field(None, description="Message optionnel (ex: Quelle taille pour moi ?)")
    history: list[SizeAdviceHistoryTurn] = Field(
        default_factory=list,
        max_length=24,
        description="Échanges précédents sur ce vêtement (user / assistant), pour cohérence",
    )
    description: str | None = Field(None, description="Description du vêtement")
    category: str | None = Field(None, description="Catégorie du vêtement")
    gender: str | None = Field(None, description="Genre du vêtement")
    brand: str | None = Field(None, description="Marque du vêtement")


class SizeAdviceResponse(BaseModel):
    """Réponse du conseiller taille."""

    reply: str = Field(..., description="Recommandation de taille")
    cart_added: bool = Field(False, description="Article ajouté au panier par l’agent")
    cart_size: str | None = Field(None, description="Taille utilisée si cart_added")
    cart_error: str | None = Field(None, description="Erreur si ajout panier demandé mais impossible")


def _build_profile_prompt(profile: UserProfile | None) -> str:
    """
    Construit la phrase de personnalisation pour le prompt.
    Format : 'Tu conseilles [Nom], taille [Top/Bottom], style [Style]. Il/Elle déteste le [Couleurs]'
    """
    if not profile:
        return ""
    parts = []
    name = profile.first_name or "l'utilisateur"
    parts.append(f"Tu conseilles {name}")
    if profile.top_size or profile.bottom_size:
        size_str = "/".join(filter(None, [profile.top_size, profile.bottom_size]))
        parts.append(f", taille {size_str}")
    if profile.style_preference:
        parts.append(f", style {profile.style_preference}")
    if profile.disliked_colors:
        colors = ", ".join(profile.disliked_colors)
        parts.append(f". Il/Elle déteste le {colors}")
    if profile.height_cm or profile.weight_kg:
        morpho = []
        if profile.height_cm:
            morpho.append(f"{profile.height_cm} cm")
        if profile.weight_kg:
            morpho.append(f"{profile.weight_kg} kg")
        parts.append(f" Morphologie : {', '.join(morpho)}.")
    return "Contexte utilisateur : " + "".join(parts).lstrip(", ") + "\n\n"


def _build_user_measures(profile: UserProfile | None) -> dict[str, float]:
    """Extrait les mesures pour le Fit Advisor."""
    if not profile:
        return {}
    return {
        k: v
        for k, v in {
            "chest_circ": profile.chest_circ,
            "waist_circ": profile.waist_circ,
            "hip_circ": profile.hip_circ,
            "arm_length": profile.arm_length,
            "inside_leg": profile.inside_leg,
        }.items()
        if v is not None
    }


def _garment_to_source_dict(g: dict) -> dict:
    """Payload « source » pour le front (grille + fiches)."""
    return {
        "id": g.get("id"),
        "name": g["name"],
        "brand": g["brand"],
        "category": g["category"],
        "gender": g.get("gender"),
        "description": g.get("description") or "",
        "price": g.get("price"),
        "stock": g.get("stock"),
        "image_url": g.get("image_url"),
        "size_guide": g.get("size_guide"),
    }


def _build_context(garments: list[dict]) -> str:
    """Construit le contexte à injecter dans le prompt."""
    if not garments:
        return "Aucun article trouvé dans le catalogue pour cette demande."

    lines = []
    for g in garments:
        price_str = f" - {g['price']}€" if g.get("price") is not None else ""
        lines.append(f"- {g['name']} ({g['brand']}) - {g['category']}{price_str}: {g['description']}")
    return "Articles du catalogue :\n" + "\n".join(lines)


async def _resolve_garment_id(
    db: AsyncSession,
    garment_id: int | None,
    garment_name: str,
) -> int | None:
    """Identifiant catalogue : priorité à garment_id, sinon nom exact."""
    if garment_id is not None:
        r = await db.execute(select(Garment).where(Garment.id == garment_id))
        g = r.scalar_one_or_none()
        if g:
            return g.id
    r2 = await db.execute(select(Garment).where(Garment.name == garment_name))
    g2 = r2.scalar_one_or_none()
    return g2.id if g2 else None


async def _fetch_user_profile(
    db: AsyncSession,
    authorization: str | None,
) -> UserProfile | None:
    """Retourne le UserProfile si l'utilisateur est connecté, sinon None."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    email = decode_access_token(token)
    if not email:
        return None
    result = await db.execute(
        select(User).where(User.email == email).options(selectinload(User.user_profile))
    )
    user = result.scalar_one_or_none()
    return user.user_profile if user and user.user_profile else None


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> ChatResponse:
    """
    Chat RAG : conseil personnalisé basé sur le catalogue.
    Si connecté, utilise le UserProfile pour personnaliser (conseils morphologiques, exclusion des couleurs).
    Les filtres price_min/price_max s'appliquent à la requête SQL.
    """
    settings = get_settings()

    if not settings.mistral_api_key:
        raise HTTPException(
            status_code=503,
            detail="MISTRAL_API_KEY non configurée. Impossible d'utiliser le chat.",
        )

    # 0. Profil utilisateur (optionnel, pour personnalisation)
    user_profile = await _fetch_user_profile(db, authorization)

    # 1. Retrieval : recherche sémantique + filtres genre et prix
    try:
        garments = await get_relevant_garments(
            db=db,
            query=body.message,
            api_key=settings.mistral_api_key,
            limit=8,
            price_min=body.price_min,
            price_max=body.price_max,
            gender=body.gender,
        )
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
            detail=f"Erreur lors de la recherche : {str(e)}",
        ) from e

    # 2. Augmentation : contexte + profil utilisateur
    context = _build_context(garments)
    profile_prompt = _build_profile_prompt(user_profile)
    system_content = f"{SYSTEM_PROMPT_BASE}\n\n{profile_prompt}{context}"

    # Instruction pour exclure les couleurs si profil présent
    if user_profile and user_profile.disliked_colors:
        system_content += f"\n\nIMPORTANT : Ne recommande AUCUN article dont la description ou le nom mentionne ces couleurs : {', '.join(user_profile.disliked_colors)}."

    # 4. Génération : appel Mistral Chat
    try:
        async with Mistral(api_key=settings.mistral_api_key) as client:
            res = await traced_mistral_call(
                "chat.complete.rag",
                client.chat.complete_async(
                    model=settings.mistral_chat_model,
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": body.message},
                    ],
                    temperature=0.25,
                    max_tokens=settings.mistral_rag_max_tokens,
                ),
            )
        reply = res.choices[0].message.content or ""
    except MistralCallTimeoutError:
        raise HTTPException(
            status_code=504,
            detail="L'API Mistral (chat) a mis trop longtemps à répondre.",
        ) from None
    except Exception as e:
        mapped = mistral_exception_to_user_response(e)
        if mapped:
            raise HTTPException(status_code=mapped[0], detail=mapped[1]) from e
        raise HTTPException(
            status_code=503,
            detail=f"Erreur API Mistral : {str(e)}",
        ) from e

    # 5. Grille = uniquement les articles dont le nom exact apparaît dans la réponse du modèle
    reply_lower = reply.lower()
    sources: list[dict] = []
    for g in garments:
        name = g.get("name", "")
        if name and name.lower() in reply_lower:
            sources.append(_garment_to_source_dict(g))

    return ChatResponse(reply=reply, sources=sources)


@router.post("/size-advice", response_model=SizeAdviceResponse)
async def size_advice(
    body: SizeAdviceRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> SizeAdviceResponse:
    """
    Conseil taille pour un vêtement spécifique.
    Utilise les mesures du profil (chest_circ, waist_circ, hip_circ) pour recommander une taille.
    Le champ ``history`` (tours user/assistant précédents) permet de rester cohérent sur la même fiche.
    Nécessite une connexion et un profil avec mesures.
    """
    user_profile = await _fetch_user_profile(db, authorization)
    if not user_profile:
        return SizeAdviceResponse(
            reply="Connectez-vous et renseignez vos mesures (poitrine, taille, hanches) dans votre profil pour obtenir un conseil de taille personnalisé."
        )

    user_measures = _build_user_measures(user_profile)
    if not user_measures:
        return SizeAdviceResponse(
            reply="Renseignez vos mesures (poitrine, taille, hanches) dans votre profil pour obtenir un conseil de taille personnalisé."
        )

    if not body.size_guide:
        return SizeAdviceResponse(
            reply="Ce vêtement n'a pas de guide des tailles disponible."
        )

    settings = get_settings()
    if not settings.mistral_api_key:
        return SizeAdviceResponse(
            reply="Service de conseil taille temporairement indisponible (MISTRAL_API_KEY manquante)."
        )

    conversation = [t.model_dump() for t in body.history][-20:]

    fit = await get_fit_advisor_result(
        garment_name=body.garment_name,
        user_measures=user_measures,
        size_guide=body.size_guide,
        api_key=settings.mistral_api_key,
        chat_model=settings.mistral_chat_model,
        user_message=body.message,
        garment_description=body.description,
        garment_category=body.category,
        garment_gender=body.gender,
        garment_brand=body.brand,
        conversation_history=conversation,
    )

    reply_text = fit.reply
    cart_added = False
    cart_size_out: str | None = None
    cart_error: str | None = None

    if fit.add_to_cart and fit.cart_size:
        gid = await _resolve_garment_id(db, body.garment_id, body.garment_name)
        if gid is None:
            cart_error = "Article introuvable pour le panier."
        else:
            try:
                await merge_line_into_cart(
                    db,
                    user_profile.user_id,
                    gid,
                    fit.cart_size,
                    1,
                )
                cart_added = True
                cart_size_out = fit.cart_size
                reply_text = (
                    reply_text
                    + f"\n\n✓ Ajouté à votre panier (taille {fit.cart_size})."
                )
            except CartMergeError as e:
                cart_error = e.detail
                reply_text = reply_text + f"\n\n_(Impossible d’ajouter au panier : {e.detail})_"

    return SizeAdviceResponse(
        reply=reply_text,
        cart_added=cart_added,
        cart_size=cart_size_out,
        cart_error=cart_error,
    )
