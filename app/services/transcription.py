"""Transcription audio via Mistral Voxtral uniquement."""

import asyncio

from mistralai.client import Mistral

from app.core.mistral_trace import traced_mistral_call


def _transcribe_sync(audio_bytes: bytes, filename: str, api_key: str, language: str) -> str:
    """Transcription synchrone via Mistral Voxtral."""
    with Mistral(api_key=api_key) as client:
        res = client.audio.transcriptions.complete(
            model="voxtral-mini-latest",
            file={"file_name": filename, "content": audio_bytes},
            language=language,
            diarize=False,
        )
    return (res.text or "").strip()


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "recording.webm",
    api_key: str | None = None,
    language: str = "fr",
) -> str:
    """
    Transcrit un fichier audio en texte via Mistral Voxtral.

    Args:
        audio_bytes: Contenu binaire du fichier audio.
        filename: Nom du fichier (pour le type MIME).
        api_key: Clé API Mistral.
        language: Code langue (fr, en, etc.).

    Returns:
        Texte transcrit.
    """
    if not api_key:
        return ""

    return await traced_mistral_call(
        "audio.transcriptions.complete",
        asyncio.to_thread(
            _transcribe_sync,
            audio_bytes,
            filename,
            api_key,
            language,
        ),
    )
