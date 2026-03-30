"""Script d'injection du catalogue de vêtements avec embeddings Mistral.

Images :
- Si ``image_url`` est renseignée dans ``catalog.json``, elle est utilisée telle quelle.
- Sinon recherche DuckDuckGo Images avec requêtes orientées mode + score de pertinence
  (titre, source, URL) pour éviter au maximum les images incohérentes.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from duckduckgo_search import DDGS
from mistralai.client import Mistral
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path.cwd()))

from app.core.config import get_settings
from app.core.mistral_trace import MistralCallTimeoutError, traced_mistral_call
from app.models.garment import Garment

# Pause entre requêtes DDG (évite blocage / rate limit)
IMAGE_SEARCH_DELAY_SEC = 2.0

# Score minimal pour accepter tout de suite un résultat ; sinon on essaie d’autres requêtes.
MIN_SCORE_CONFIDENT = 6
# Score minimal absolu pour prendre le « meilleur » candidat avant Picsum.
MIN_SCORE_ACCEPT = 3

CATEGORY_EN = {
    "Formal": "formal wear outfit",
    "Casual": "casual fashion clothing",
    "Sport": "sportswear athletic wear",
    "Outdoor": "outdoor jacket hiking",
    "Accessories": "fashion accessories",
    "Loungewear": "loungewear homewear",
}

STOPWORDS = frozenset(
    {
        "pour",
        "avec",
        "sans",
        "dans",
        "the",
        "and",
        "de",
        "du",
        "des",
        "la",
        "le",
        "les",
        "un",
        "une",
        "aux",
        "est",
    }
)


def _sig_words(text: str) -> list[str]:
    """Mots significatifs (évite articles trop courts)."""
    raw = re.findall(r"[a-zàâäéèêëïîôùûœçA-ZÀÂÄÉÈÊËÏÎÔÙÛŒÇ0-9]+", text.lower())
    return [w for w in raw if len(w) >= 3 and w not in STOPWORDS]


def _reject_image_url(url: str) -> bool:
    if not url or not url.startswith("http"):
        return True
    u = url.lower()
    junk = (
        "favicon",
        "avatar",
        "/logo",
        "sprite",
        "icon_",
        "placeholder",
        "1x1",
        "blank.",
        "spacer",
    )
    return any(x in u for x in junk)


def _result_haystack(r: dict) -> str:
    return " ".join(
        str(r.get(k) or "")
        for k in ("title", "url", "image", "thumbnail", "source")
    ).lower()


def _compact_alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9àâäéèêëïîôùûç]+", "", s.lower())


def _score_image_result(r: dict, image_url: str, name: str, brand: str, category: str) -> int:
    if _reject_image_url(image_url):
        return -1000
    h = _result_haystack(r) + " " + image_url.lower()
    h_compact = _compact_alnum(h)
    score = 0
    # Marque collée (ex. DenimCraft, LuxeOndine) souvent présente telle quelle dans l’URL / titre
    bc = _compact_alnum(brand)
    if len(bc) >= 5 and bc in h_compact:
        score += 8
    brand_spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", brand)
    for w in _sig_words(brand_spaced):
        if w in h:
            score += 4
    for w in _sig_words(name):
        if w in h:
            score += 2
    cat_hint = CATEGORY_EN.get(category, category)
    for w in _sig_words(cat_hint)[:5]:
        if len(w) >= 4 and w in h:
            score += 1
    return score


def _build_queries(name: str, brand: str, category: str) -> list[str]:
    ce = CATEGORY_EN.get(category, category)
    # Ordre : le plus spécifique d’abord (marque + produit + contexte mode)
    return [
        f"{brand} {name} fashion clothing",
        f"{name} {brand} wear",
        f"{name} {ce}",
        f"{brand} {name}",
        f"{name} style {ce.split()[0] if ce else 'fashion'}",
        name,
    ]


def search_best_product_image(name: str, brand: str, category: str) -> tuple[str | None, str]:
    """
    Retourne (url, libellé diagnostic).
    Parcourt plusieurs requêtes et type_image ; choisit l’image au meilleur score de pertinence.
    """
    best_url: str | None = None
    best_score = -9999
    best_note = ""

    for type_image in ("photo", None):
        for q in _build_queries(name, brand, category):
            try:
                ddgs = DDGS()
                results = list(
                    ddgs.images(
                        keywords=q,
                        region="wt-wt",
                        safesearch="moderate",
                        max_results=30,
                        **({"type_image": type_image} if type_image else {}),
                    )
                )
            except Exception:
                results = []

            for r in results:
                url = r.get("image") or r.get("thumbnail")
                if not url:
                    continue
                sc = _score_image_result(r, url, name, brand, category)
                if sc > best_score:
                    best_score = sc
                    best_url = url
                    best_note = f"DDG score={sc} q={q[:50]!r}"

            if best_score >= MIN_SCORE_CONFIDENT and best_url:
                return best_url, best_note

    if best_url and best_score >= MIN_SCORE_ACCEPT:
        return best_url, best_note + " (meilleur candidat)"
    return None, f"aucun candidat fiable (max_score={best_score})"


def _picsum_placeholder(name: str) -> str:
    seed = re.sub(r"[^a-zA-Z0-9]", "", name)[:50] or "garment"
    return f"https://picsum.photos/seed/{seed}/640/480"


async def _embedding_for_text(client: Mistral, text: str):
    return await traced_mistral_call(
        "embeddings.create.seed",
        asyncio.to_thread(
            client.embeddings.create,
            model=get_settings().mistral_embed_model,
            inputs=[text],
        ),
    )


async def _repair_missing_embeddings(session: AsyncSession, client: Mistral) -> int:
    result = await session.execute(select(Garment).where(Garment.embedding.is_(None)))
    rows = list(result.scalars().all())
    if not rows:
        return 0
    print(f"[seed] {len(rows)} article(s) sans embedding — calcul via Mistral...")
    fixed = 0
    for g in rows:
        text = (g.description or "").strip() or f"{g.name} {g.brand} {g.category}"
        try:
            res = await _embedding_for_text(client, text)
        except MistralCallTimeoutError as e:
            print(f"⚠️ Timeout embedding id={g.id} ({g.name}): {e}")
            continue
        except Exception as e:
            print(f"⚠️ Erreur embedding id={g.id} ({g.name}): {e}")
            continue
        g.embedding = res.data[0].embedding
        fixed += 1
        print(f"  ✓ {g.name}")
    await session.commit()
    return fixed


def _normalize_catalog_image_url(item: dict) -> str | None:
    u = item.get("image_url")
    if u is None or (isinstance(u, str) and not u.strip()):
        return None
    return str(u).strip()


async def seed() -> None:
    settings = get_settings()

    engine = create_async_engine(
        settings.database_url,
        connect_args={
            "timeout": settings.database_connect_timeout_seconds,
            "command_timeout": settings.database_command_timeout_seconds,
        },
    )
    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with AsyncSessionLocal() as session:
        n_total = (await session.execute(select(func.count(Garment.id)))).scalar() or 0
        n_null = (
            await session.execute(
                select(func.count(Garment.id)).where(Garment.embedding.is_(None))
            )
        ).scalar() or 0

    if n_total > 0 and n_null == 0:
        print("Database already seeded. Skipping...")
        return

    if not settings.mistral_api_key:
        if n_null > 0:
            print(
                "❌ MISTRAL_API_KEY manquante : impossible de calculer les embeddings manquants."
            )
        elif n_total == 0:
            print("❌ Erreur : MISTRAL_API_KEY manquante dans le fichier .env")
        return

    client = Mistral(api_key=settings.mistral_api_key)

    if n_total > 0 and n_null > 0:
        async with AsyncSessionLocal() as session:
            n_fixed = await _repair_missing_embeddings(session, client)
        print(f"\n✨ [seed] Embeddings complétés pour {n_fixed} article(s).")
        return

    app_dir = Path(__file__).resolve().parent.parent
    data_path = app_dir / "data" / "catalog.json"
    if not data_path.is_file():
        print(f"❌ Erreur : Fichier {data_path} introuvable.")
        return

    with data_path.open(encoding="utf-8") as f:
        items = json.load(f)

    async with AsyncSessionLocal() as session:
        print(
            f"🚀 Import de {len(items)} articles (images : JSON > DuckDuckGo scoré > Picsum)..."
        )

        for i, item in enumerate(items):
            try:
                print(f"--- [{i+1}/{len(items)}] {item['name']} ---")

                image_url = _normalize_catalog_image_url(item)
                if image_url:
                    print(f"    📷 Image catalogue (JSON)")
                else:
                    url, note = await asyncio.to_thread(
                        search_best_product_image,
                        item["name"],
                        item["brand"],
                        item.get("category", ""),
                    )
                    if url:
                        image_url = url
                        print(f"    📷 {note}")
                    else:
                        image_url = _picsum_placeholder(item["name"])
                        print(f"    📷 Picsum (DDG : {note})")
                    await asyncio.sleep(IMAGE_SEARCH_DELAY_SEC)

                try:
                    res = await _embedding_for_text(client, item["description"])
                except MistralCallTimeoutError as e:
                    print(f"⚠️ Timeout Mistral sur {item['name']}: {e}")
                    continue
                vector = res.data[0].embedding

                raw_guide = item.get("size_guide")
                size_guide = None
                if raw_guide is not None:
                    if isinstance(raw_guide, dict):
                        size_guide = raw_guide
                    elif isinstance(raw_guide, str):
                        try:
                            parsed = json.loads(raw_guide)
                            size_guide = parsed if isinstance(parsed, dict) else None
                        except (json.JSONDecodeError, TypeError):
                            pass
                    if size_guide is not None and not isinstance(size_guide, dict):
                        size_guide = None

                new_garment = Garment(
                    name=item["name"],
                    brand=item["brand"],
                    category=item["category"],
                    gender=item.get("gender"),
                    description=item["description"],
                    price=item.get("price"),
                    stock=item.get("stock"),
                    image_url=image_url,
                    size_guide=size_guide,
                    embedding=vector,
                )
                session.add(new_garment)
                print(f"✅ {item['name']} ajouté.")

            except Exception as e:
                print(f"⚠️ Erreur sur {item['name']}: {e}")

        await session.commit()
        print("\n✨ Catalogue vectorisé.")


if __name__ == "__main__":
    asyncio.run(seed())
