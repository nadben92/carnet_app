"""API d'extraction de guides de tailles depuis des images (vision Mistral)."""

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import get_settings
from app.core.mistral_trace import MistralCallTimeoutError
from app.services.size_extractor import extract_size_guide_from_image

router = APIRouter(prefix="/size-extract", tags=["size-extract"])


@router.post("")
async def extract_size_guide(image: UploadFile = File(...)):
    """
    Extrait un guide de tailles structuré depuis une image de tableau de tailles.
    Utilise le modèle vision configuré (``MISTRAL_CHAT_MODEL``, ex. mistral-small-latest).
    Retourne un JSON : {"S": {"chest": [88, 92], "waist": [76, 80], "hip": [92, 96]}, ...}
    """
    settings = get_settings()
    if not settings.mistral_api_key:
        raise HTTPException(
            status_code=503,
            detail="MISTRAL_API_KEY non configurée.",
        )
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Le fichier doit être une image (JPEG, PNG, etc.).",
        )
    try:
        data = await image.read()
        result = await extract_size_guide_from_image(
            image_source=data,
            api_key=settings.mistral_api_key,
            vision_model=settings.mistral_chat_model,
        )
        return result
    except MistralCallTimeoutError:
        raise HTTPException(
            status_code=504,
            detail="L'API Mistral (vision) a mis trop longtemps à répondre.",
        ) from None
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Erreur lors de l'extraction : {str(e)}",
        ) from e
