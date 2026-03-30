"""Messages HTTP lisibles pour les erreurs renvoyées par l’API Mistral."""

from __future__ import annotations


def mistral_exception_to_user_response(exc: BaseException) -> tuple[int, str] | None:
    """
    Si l’exception correspond à un cas connu (quota, capacité, clé), retourne
    (status_code, message_fr) pour HTTPException. Sinon None (laisser le handler générique).
    """
    raw = str(exc)
    low = raw.lower()
    status = getattr(exc, "status_code", None)

    if status == 429 or "429" in raw:
        if (
            "capacity" in low
            or "3505" in raw
            or "service_tier" in low
            or "service tier" in low
        ):
            return (
                503,
                "L’API Mistral est temporairement saturée pour ce modèle (capacité ou débit). "
                "Réessayez dans quelques minutes. Vérifiez aussi votre offre et vos quotas sur "
                "https://console.mistral.ai .",
            )
        return (
            503,
            "Trop de requêtes vers l’API Mistral (limite de débit). Réessayez dans quelques instants.",
        )

    if status == 401 or "401" in raw or "unauthorized" in low or "invalid api key" in low:
        return (
            503,
            "Clé API Mistral refusée. Vérifiez MISTRAL_API_KEY dans votre configuration.",
        )

    if status == 402 or "402" in raw or "billing" in low or "payment required" in low:
        return (
            503,
            "Problème de facturation ou de crédit côté Mistral. Consultez https://console.mistral.ai .",
        )

    return None
