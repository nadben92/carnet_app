"""API de transcription audio via Mistral Voxtral."""

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.mistral_trace import MistralCallTimeoutError
from app.services.transcription import transcribe_audio

router = APIRouter(prefix="/audio", tags=["audio"])

class TranscribeResponse(BaseModel):
    """Réponse transcription."""

    text: str = Field(..., description="Texte transcrit")
    bytes_received: int = Field(..., ge=0)
    status: str = Field(default="ok")


ALLOWED_AUDIO_TYPES = {
    "audio/webm",
    "audio/webm;codecs=opus",
    "video/webm",
    "audio/mp4",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/ogg",
}


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(file: UploadFile = File(...)) -> TranscribeResponse:
    """
    Transcrit un fichier audio en texte via Mistral Voxtral.
    Accepte : webm, mp4, mp3, wav, ogg.
    """
    settings = get_settings()
    if not settings.mistral_api_key:
        raise HTTPException(
            status_code=503,
            detail="MISTRAL_API_KEY non configurée.",
        )
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_AUDIO_TYPES and not content_type.startswith("audio/") and "webm" not in content_type:
        raise HTTPException(
            status_code=400,
            detail="Le fichier doit être un fichier audio (webm, mp4, mp3, wav, ogg).",
        )
    try:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Fichier audio vide.")
        ext = "webm"
        if "mp4" in content_type or "m4a" in content_type:
            ext = "m4a"
        elif "mpeg" in content_type or "mp3" in content_type:
            ext = "mp3"
        elif "wav" in content_type:
            ext = "wav"
        elif "ogg" in content_type:
            ext = "ogg"
        filename = f"recording.{ext}"
        text = await transcribe_audio(
            audio_bytes=data,
            filename=filename,
            api_key=settings.mistral_api_key,
            language="fr",
        )
        return TranscribeResponse(
            text=text,
            bytes_received=len(data),
            status="ok",
        )
    except HTTPException:
        raise
    except MistralCallTimeoutError:
        raise HTTPException(
            status_code=504,
            detail="L'API Mistral (transcription) a mis trop longtemps à répondre.",
        ) from None
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Erreur lors de la transcription : {str(e)}",
        ) from e
