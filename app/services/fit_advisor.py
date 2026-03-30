"""Agent Fit Advisor - conseil de taille + ajout panier sur demande explicite."""

import re
from dataclasses import dataclass
from typing import Any

from mistralai.client import Mistral

from app.core.mistral_trace import MistralCallTimeoutError, traced_mistral_call
from app.services.size_extractor import _extract_json_from_text

FIT_BLOCK_START = "---FIT---"
FIT_BLOCK_END = "---END---"

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
4. Cite clairement la taille recommandée dans ton texte (en français naturel).

RÈGLES CARACTÉRISTIQUES :
5. Si description, catégorie, genre ou marque sont fournis, ajoute 1-2 phrases (coupe, style, entretien, associations).
6. Ton texte principal doit être en français courant, chaleureux, 3 à 5 phrases. INTERDIT dans cette partie : JSON, accolades { }, crochets de structure, guillemets autour de champs techniques.

PANIER (très important) :
7. add_to_cart: true (dans le bloc technique ci-dessous) UNIQUEMENT si l'utilisateur demande EXPLICITEMENT d'ajouter l'article au panier ou de l'acheter / le commander dans ce message.
   Exemples : "ajoute au panier", "mets-le dans mon panier", "je le prends", "commande-le", "ajoute-le", "je veux l'acheter en taille M".
8. Jamais d'ajout pour une simple question ("quelle taille ?", "ça taille comment ?") sans intention d'achat claire.
9. Si add_to_cart est true, cart_size DOIT être EXACTEMENT une des clés listées dans « Clés de taille valides » (même casse, même orthographe).
10. Si l'utilisateur indique une taille dans sa demande d'ajout (ex: "ajoute en L"), utilise cette taille si c'est une clé valide ; sinon la taille que tu recommandes selon les mesures.
11. Sinon add_to_cart: false et cart_size vide.

FORMAT DE SORTIE (obligatoire, deux parties) :
A) D'abord ton conseil en français (plusieurs phrases). Aucun JSON, aucune ligne qui commence par add_to_cart ou cart_size ici.

B) Immédiatement après, sur des lignes séparées, ce bloc EXACT (sans markdown autour) :

---FIT---
add_to_cart: false
cart_size:
---END---

Si l'utilisateur demande l'ajout au panier et une taille est valide, utilise par exemple :
---FIT---
add_to_cart: true
cart_size: M
---END---

Remplace M par une clé valide. Si pas d'ajout : add_to_cart: false et laisse cart_size: vide après les deux-points.
"""


def _strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _parse_fit_delimiter_block(raw: str) -> tuple[str, bool, str | None] | None:
    """Extrait (texte_utilisateur, add_to_cart, cart_size) si le bloc ---FIT--- est présent."""
    if FIT_BLOCK_START not in raw or FIT_BLOCK_END not in raw:
        return None
    before, _, rest = raw.partition(FIT_BLOCK_START)
    meta_section, _, _ = rest.partition(FIT_BLOCK_END)
    main = before.strip()
    add_to_cart = False
    cart_size: str | None = None
    for line in meta_section.strip().splitlines():
        line = line.strip()
        low = line.lower()
        if low.startswith("add_to_cart:"):
            val = line.split(":", 1)[1].strip().lower()
            add_to_cart = val in ("true", "1", "yes", "oui")
        elif low.startswith("cart_size:"):
            v = line.split(":", 1)[1].strip()
            if v and v.lower() not in ("null", "none", ""):
                cart_size = v
            else:
                cart_size = None
    if not main:
        main = re.sub(
            r"---FIT---[\s\S]*?---END---",
            "",
            raw,
            flags=re.DOTALL,
        ).strip()
    if not main:
        return None
    return main, add_to_cart, cart_size


def _parse_json_fit_legacy(raw: str) -> tuple[str, bool, str | None] | None:
    parsed = _extract_json_from_text(raw)
    if not parsed or not isinstance(parsed, dict):
        return None
    reply = (parsed.get("reply") or "").strip()
    if not reply:
        return None
    # Évite d'afficher du JSON si le modèle a mis tout le paquet dans "reply"
    if reply.startswith("{") and '"reply"' in reply:
        inner = _extract_json_from_text(reply)
        if inner and isinstance(inner, dict) and inner.get("reply"):
            reply = str(inner["reply"]).strip()
    add_to_cart = parsed.get("add_to_cart") is True
    cart_size = parsed.get("cart_size")
    if cart_size is not None:
        cart_size = str(cart_size).strip() or None
    return reply, add_to_cart, cart_size


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
    chat_model: str = "mistral-small-latest",
    user_message: str | None = None,
    garment_description: str | None = None,
    garment_category: str | None = None,
    garment_gender: str | None = None,
    garment_brand: str | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> FitAdvisorResult:
    """
    Conseil taille + détection d'une demande d'ajout au panier.
    Sortie modèle : prose française puis bloc ---FIT--- / ---END--- ; repli JSON historique.
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
            "content": (
                f"Message actuel de l'utilisateur : {user_pref}\n\n"
                "Réponds avec ton conseil en français puis le bloc ---FIT--- ... ---END--- "
                "comme indiqué dans les instructions système (add_to_cart et cart_size)."
            ),
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
        raw_text = _strip_code_fences(res.choices[0].message.content or "")
    except MistralCallTimeoutError:
        return FitAdvisorResult(
            reply="Délai dépassé pour le conseil taille. Réessayez dans un instant.",
        )
    except Exception as e:
        return FitAdvisorResult(reply=f"Erreur lors du conseil : {str(e)}")

    parsed_tuple: tuple[str, bool, str | None] | None = _parse_fit_delimiter_block(
        raw_text
    )
    if parsed_tuple is None:
        legacy = _parse_json_fit_legacy(raw_text)
        if legacy is not None:
            parsed_tuple = legacy
    if parsed_tuple is None:
        stripped = raw_text.strip()
        # Texte naturel sans bloc technique : on l’affiche tel quel (pas d’ajout panier auto)
        if stripped and not stripped.startswith("{"):
            return FitAdvisorResult(reply=stripped)
        reply_fallback = stripped
        if reply_fallback.startswith("{"):
            reply_fallback = (
                "Je n’ai pas pu formater la réponse correctement. "
                "Reformulez votre question ou réessayez dans un instant."
            )
        return FitAdvisorResult(reply=reply_fallback or "Réponse invalide du conseiller.")

    reply, add_to_cart, cart_size = parsed_tuple

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
    chat_model: str = "mistral-small-latest",
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
