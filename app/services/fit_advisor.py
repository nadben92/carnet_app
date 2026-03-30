"""Agent Fit Advisor - conseil de taille + ajout panier sur demande explicite."""

from dataclasses import dataclass
from typing import Any

from mistralai.client import Mistral

from app.core.mistral_trace import MistralCallTimeoutError, traced_mistral_call
from app.services.size_extractor import _extract_json_from_text

FIT_ADVISOR_SYSTEM = """Tu es un expert conseiller taille et style pour un service de mode. Tu compares les mesures d'un utilisateur au guide des tailles du vêtement, et tu donnes des conseils sur le vêtement.

MÉMOIRE / COHÉRENCE :
0. Un historique de conversation peut précéder le message actuel : il s'agit toujours du MÊME article. Tiens compte de ce que tu as déjà dit (taille conseillée, préférences ample/serré, remarques). Ne contredis pas tes réponses précédentes sans raison valable. Si l'utilisateur change d'avis (ex. passe de « ample » à « près du corps ») ou apporte une nouvelle info, tu peux ajuster ta recommandation et l'expliquer brièvement en une phrase.

RÈGLES TAILLE :
1. Compare les mesures utilisateur aux plages [min, max] du size_guide pour chaque taille.
2. Si les mesures correspondent clairement à une taille, recommande cette taille.
3. Si l'utilisateur est ENTRE DEUX tailles :
   - Préférence GRAND / ample / confortable / oversize → taille SUPÉRIEURE.
   - Préférence SERRÉ / ajusté / slim → taille INFÉRIEURE.
   - Sans préférence → taille supérieure pour le confort.
4. Cite la taille recommandée clairement dans le champ "reply".

RÈGLES CARACTÉRISTIQUES :
5. Si description, catégorie, genre ou marque sont fournis, ajoute 1-2 phrases (coupe, style, entretien, associations).
6. Le champ "reply" doit rester naturel et chaleureux, 3-5 phrases au total.

PANIER (très important) :
7. Mets "add_to_cart": true UNIQUEMENT si l'utilisateur demande EXPLICITEMENT d'ajouter l'article au panier ou de l'acheter / le commander dans ce message.
   Exemples qui déclenchent l'ajout : "ajoute au panier", "mets-le dans mon panier", "je le prends", "commande-le", "ajoute-le", "je veux l'acheter en taille M".
8. Ne mets JAMAIS "add_to_cart": true pour une simple question ("quelle taille ?", "ça taille comment ?") sans intention d'achat claire.
9. Si "add_to_cart" est true, "cart_size" DOIT être EXACTEMENT une des clés listées dans "Clés de taille valides" du message utilisateur (même casse, même orthographe).
10. Si l'utilisateur indique une taille dans sa demande d'ajout (ex: "ajoute en L"), utilise cette taille si elle est une clé valide ; sinon la taille que tu recommandes selon les mesures.
11. Si "add_to_cart" est false, mets "cart_size" à null.

FORMAT DE SORTIE :
Tu réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans texte avant ou après :
{"reply": "ton message utilisateur en français", "add_to_cart": false, "cart_size": null}
ou si ajout demandé :
{"reply": "...", "add_to_cart": true, "cart_size": "M"}
"""


@dataclass
class FitAdvisorResult:
    """Réponse structurée du conseiller taille."""

    reply: str
    add_to_cart: bool = False
    cart_size: str | None = None


async def get_fit_advisor_result(
    garment_name: str,
    user_measures: dict[str, float],
    size_guide: dict[str, Any] | None,
    api_key: str | None = None,
    chat_model: str = "mistral-large-latest",
    user_message: str | None = None,
    garment_description: str | None = None,
    garment_category: str | None = None,
    garment_gender: str | None = None,
    garment_brand: str | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> FitAdvisorResult:
    """
    Conseil taille + détection d'une demande d'ajout au panier (JSON Mistral).
    """
    if not size_guide or not isinstance(size_guide, dict):
        return FitAdvisorResult(
            reply="Guide des tailles non disponible pour ce vêtement.",
        )

    user_chest = user_measures.get("chest_circ") or user_measures.get("chest")
    user_waist = user_measures.get("waist_circ") or user_measures.get("waist")
    user_hip = user_measures.get("hip_circ") or user_measures.get("hip")

    if user_chest is None and user_waist is None and user_hip is None:
        return FitAdvisorResult(
            reply="Aucune mesure utilisateur fournie (poitrine, taille, hanches) pour le conseil.",
        )

    has_usable = any(
        isinstance(sd, dict) and any(sd.get(k) for k in ("chest", "waist", "hip"))
        for sd in size_guide.values()
    )
    if not has_usable:
        return FitAdvisorResult(
            reply="Guide des tailles non compatible avec les mesures (poitrine, taille, hanches).",
        )

    if not api_key:
        return FitAdvisorResult(
            reply="Service de conseil taille temporairement indisponible.",
        )

    measures_str = ", ".join(
        f"{k}: {v} cm"
        for k, v in [
            ("poitrine", user_chest),
            ("taille", user_waist),
            ("hanches", user_hip),
        ]
        if v is not None
    )
    user_pref = (user_message or "Quelle taille pour moi ?").strip()

    garment_info_parts = [f"Nom : {garment_name}"]
    if garment_brand:
        garment_info_parts.append(f"Marque : {garment_brand}")
    if garment_category:
        garment_info_parts.append(f"Catégorie : {garment_category}")
    if garment_gender:
        garment_info_parts.append(f"Genre : {garment_gender}")
    if garment_description:
        garment_info_parts.append(f"Description : {garment_description}")
    garment_info = "\n".join(garment_info_parts)

    valid_keys = [str(k) for k in size_guide.keys()]
    keys_str = ", ".join(repr(k) for k in valid_keys)

    context_block = f"""CONTEXTE ARTICLE (identique pour toute cette conversation sur cette fiche) :
{garment_info}

Mesures utilisateur : {measures_str}
Guide des tailles : {size_guide}

Clés de taille valides pour cart_size (exactement l'une d'elles si add_to_cart est true) : {keys_str}"""

    system_content = f"{FIT_ADVISOR_SYSTEM}\n\n---\n{context_block}"

    history = conversation_history or []
    history = history[-20:]
    api_messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    for turn in history:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        api_messages.append({"role": role, "content": content[:4000]})
    api_messages.append(
        {
            "role": "user",
            "content": f"Message actuel de l'utilisateur : {user_pref}\n\nRéponds uniquement avec le JSON demandé (reply, add_to_cart, cart_size).",
        }
    )

    try:
        async with Mistral(api_key=api_key) as client:
            res = await traced_mistral_call(
                "chat.complete.fit_advisor",
                client.chat.complete_async(
                    model=chat_model,
                    messages=api_messages,
                    temperature=0.2,
                ),
            )
        raw_text = (res.choices[0].message.content or "").strip()
    except MistralCallTimeoutError:
        return FitAdvisorResult(
            reply="Délai dépassé pour le conseil taille. Réessayez dans un instant.",
        )
    except Exception as e:
        return FitAdvisorResult(reply=f"Erreur lors du conseil : {str(e)}")

    parsed = _extract_json_from_text(raw_text)
    if not parsed or not isinstance(parsed, dict):
        return FitAdvisorResult(reply=raw_text or "Réponse invalide du conseiller.")

    reply = (parsed.get("reply") or "").strip()
    if not reply:
        reply = raw_text

    add_to_cart = parsed.get("add_to_cart") is True
    cart_size = parsed.get("cart_size")
    if cart_size is not None:
        cart_size = str(cart_size).strip() or None

    if add_to_cart:
        if not cart_size or cart_size not in size_guide:
            add_to_cart = False
            cart_size = None
            reply = (
                reply
                + "\n\n_(Je n’ai pas pu ajouter l’article au panier : taille non reconnue. "
                "Choisissez une taille via le bouton « Ajouter au panier ».)_"
            )

    return FitAdvisorResult(
        reply=reply,
        add_to_cart=add_to_cart,
        cart_size=cart_size,
    )


# Alias rétrocompatible pour tests / imports externes éventuels
async def get_fit_recommendation(
    garment_name: str,
    user_measures: dict[str, float],
    size_guide: dict[str, Any] | None,
    api_key: str | None = None,
    chat_model: str = "mistral-large-latest",
    user_message: str | None = None,
    garment_description: str | None = None,
    garment_category: str | None = None,
    garment_gender: str | None = None,
    garment_brand: str | None = None,
) -> str:
    r = await get_fit_advisor_result(
        garment_name=garment_name,
        user_measures=user_measures,
        size_guide=size_guide,
        api_key=api_key,
        chat_model=chat_model,
        user_message=user_message,
        garment_description=garment_description,
        garment_category=garment_category,
        garment_gender=garment_gender,
        garment_brand=garment_brand,
        conversation_history=None,
    )
    return r.reply
