"""Service d'extraction de guides de tailles depuis des images (Pixtral OCR)."""

import base64
import json
import re
from pathlib import Path
from typing import Any

from mistralai.client import Mistral

from app.core.mistral_trace import traced_mistral_call

SIZE_EXTRACTOR_PROMPT = """Convertis ce tableau de tailles en un objet JSON pur.
Les clés sont les tailles (S, M, L ou 38, 40, etc.) et les valeurs sont les plages de mesures en cm pour la poitrine (chest), la taille (waist) et les hanches (hip).
Format attendu : {"S": {"chest": [88, 92], "waist": [76, 80], "hip": [92, 96]}, "M": {...}}
Utilise uniquement des nombres en cm. Réponds UNIQUEMENT avec le JSON, sans texte avant ou après."""

PIXTRAL_MODEL = "pixtral-12b-2409"


def _normalize_size_guide(raw: dict[str, Any]) -> dict[str, dict[str, list[float]]]:
    """
    Normalise le JSON extrait pour respecter la structure attendue.
    Clés de mesures : chest, waist, hip (en minuscules).
    Valeurs : listes [min, max] en float.
    """
    result: dict[str, dict[str, list[float]]] = {}
    measure_keys = {"chest", "waist", "hip", "poitrine", "taille", "hanches"}
    mapping = {"poitrine": "chest", "taille": "waist", "hanches": "hip"}

    for size_label, measures in raw.items():
        if not isinstance(measures, dict):
            continue
        normalized: dict[str, list[float]] = {}
        for k, v in measures.items():
            key_lower = str(k).lower().strip()
            if key_lower in mapping:
                key_lower = mapping[key_lower]
            elif key_lower not in measure_keys:
                continue
            if isinstance(v, list) and len(v) >= 2:
                try:
                    normalized[key_lower] = [float(v[0]), float(v[1])]
                except (TypeError, ValueError):
                    pass
            elif isinstance(v, (int, float)):
                normalized[key_lower] = [float(v), float(v)]
        if normalized:
            result[str(size_label).strip()] = normalized
    return result


def _extract_json_from_text(text: str) -> dict[str, Any] | None:
    """Extrait un objet JSON du texte (gère les blocs markdown ou texte brut)."""
    text = text.strip()
    # Enlever les blocs markdown ```json ... ```
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    # Chercher un objet JSON
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    end = -1
    for i, c in enumerate(text[start:], start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


async def extract_size_guide_from_image(
    image_source: str | bytes | Path,
    api_key: str,
) -> dict[str, dict[str, list[float]]]:
    """
    Extrait un guide de tailles structuré depuis une image de tableau de tailles.

    Args:
        image_source: URL publique (str), bytes de l'image, ou chemin Path vers un fichier.
        api_key: Clé API Mistral.

    Returns:
        Dict normalisé : {"S": {"chest": [88, 92], "waist": [76, 80], "hip": [92, 96]}, ...}
    """
    def _to_data_url(data: bytes, default_type: str = "image/jpeg") -> str:
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:{default_type};base64,{b64}"

    if isinstance(image_source, Path):
        with open(image_source, "rb") as f:
            image_bytes = f.read()
        image_url = _to_data_url(image_bytes)
    elif isinstance(image_source, bytes):
        image_url = _to_data_url(image_source)
    elif isinstance(image_source, str):
        if image_source.startswith(("http://", "https://")):
            image_url = image_source
        elif image_source.startswith("data:"):
            image_url = image_source
        else:
            # Supposé chemin fichier
            with open(image_source, "rb") as f:
                image_bytes = f.read()
            image_url = _to_data_url(image_bytes)
    else:
        raise ValueError("image_source doit être une URL, bytes ou Path")

    content: list[dict[str, Any]] = [
        {"type": "text", "text": SIZE_EXTRACTOR_PROMPT},
        {"type": "image_url", "image_url": image_url},
    ]

    async with Mistral(api_key=api_key) as client:
        res = await traced_mistral_call(
            "chat.complete.pixtral_size_extract",
            client.chat.complete_async(
                model=PIXTRAL_MODEL,
                messages=[{"role": "user", "content": content}],
                temperature=0.1,
            ),
        )
    reply = res.choices[0].message.content or "{}"
    raw = _extract_json_from_text(reply)
    if not raw:
        return {}
    return _normalize_size_guide(raw)
