"""Script d'injection du catalogue de vêtements avec embeddings Mistral."""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import urllib.parse
import urllib.request

from duckduckgo_search import DDGS
from mistralai.client import Mistral
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# On s'assure que le dossier parent est dans le path pour les imports app.
sys.path.insert(0, os.getcwd())

from app.core.config import get_settings
from app.core.mistral_trace import MistralCallTimeoutError, traced_mistral_call
from app.models.garment import Garment

# Délai entre les requêtes de recherche d'images (éviter le blocage)
IMAGE_SEARCH_DELAY_SEC = 1.5

# Mapping catégories FR -> EN pour meilleurs résultats DuckDuckGo
CATEGORY_EN = {
    "Formal": "formal wear suit",
    "Casual": "casual clothing",
    "Sport": "sportswear athletic",
    "Outdoor": "outdoor jacket",
    "Accessories": "fashion accessories",
    "Loungewear": "loungewear comfort",
}


def _search_ddg(keywords: str, type_image: str | None = "photo") -> str | None:
    """Recherche DuckDuckGo, retourne la première URL valide."""
    try:
        kwargs = {
            "keywords": keywords,
            "region": "wt-wt",
            "safesearch": "moderate",
            "max_results": 15,
        }
        if type_image:
            kwargs["type_image"] = type_image
        results = list(DDGS().images(**kwargs))
        for r in results:
            url = r.get("image") or r.get("thumbnail")
            if url and url.startswith("http") and "favicon" not in url.lower():
                return url
    except Exception:
        pass
    return None


def _search_bing(keywords: str) -> str | None:
    """Recherche Bing (scraping léger via urllib), retourne la première URL valide."""
    try:
        query = urllib.parse.quote_plus(keywords)
        url = f"https://www.bing.com/images/search?q={query}&form=HDRSC2&first=1"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # Bing embeds "murl":"https://..." dans le HTML
        for match in re.finditer(r'"murl"\s*:\s*"([^"]+)"', html):
            u = match.group(1).replace("\\u002f", "/")
            if u.startswith("http") and "favicon" not in u.lower() and "bing.com" not in u:
                return u
    except Exception:
        pass
    return None


def _get_picsum_fallback(name: str) -> str:
    """Fallback garanti : Picsum retourne toujours une image unique par seed."""
    seed = re.sub(r"[^a-zA-Z0-9]", "", name)[:50] or "garment"
    return f"https://picsum.photos/seed/{seed}/640/480"


def get_real_image_url(name: str, brand: str, category: str) -> tuple[str, str]:
    """
    Recherche une image réelle. Stratégie multi-sources :
    1. DuckDuckGo avec plusieurs requêtes (FR + EN)
    2. Bing (bing-image-urls) si DuckDuckGo échoue
    3. Fallback Picsum (garantit toujours une image)
    """
    category_en = CATEGORY_EN.get(category, category)
    queries = [
        f"{name} {brand} fashion",
        f"{name} {category_en}",
        f"{brand} {name} product",
        name,
        f"{name} clothing",
    ]
    for q in queries:
        url = _search_ddg(q)
        if url:
            return (url, "DuckDuckGo")
    for q in queries[:3]:
        url = _search_ddg(q, type_image=None)
        if url:
            return (url, "DuckDuckGo")
    # Fallback Bing
    for q in queries:
        url = _search_bing(q)
        if url:
            return (url, "Bing")
    return (_get_picsum_fallback(name), "Picsum (fallback)")


async def seed() -> None:
    settings = get_settings()

    if not settings.mistral_api_key:
        print("❌ Erreur : MISTRAL_API_KEY manquante dans le fichier .env")
        return

    # Initialisation Mistral & DB
    client = Mistral(api_key=settings.mistral_api_key)
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

    # 1. Charger le JSON (chemin depuis ce module : app/data/catalog.json)
    app_dir = Path(__file__).resolve().parent.parent
    data_path = app_dir / "data" / "catalog.json"
    if not data_path.is_file():
        print(f"❌ Erreur : Fichier {data_path} introuvable.")
        return

    with data_path.open(encoding="utf-8") as f:
        items = json.load(f)

    async with AsyncSessionLocal() as session:
        # 2. Vérifier si la DB est déjà remplie
        result = await session.execute(select(func.count(Garment.id)))
        count = result.scalar() or 0

        if count > 0:
            print(
                f"✅ La base contient déjà {count} articles. Seed annulé pour éviter les doublons et les frais API."
            )
            return

        print(f"🚀 Préparation de l'injection de {len(items)} articles...")

        for i, item in enumerate(items):
            try:
                print(f"--- [{i+1}/{len(items)}] {item['name']} ---")

                # 3a. Recherche d'image réelle si pas d'URL fournie
                image_url = item.get("image_url")
                if not image_url:
                    print(f"    🔍 Recherche image: {item['name']} ({item['brand']})")
                    image_url, source = await asyncio.to_thread(
                        get_real_image_url,
                        item["name"],
                        item["brand"],
                        item.get("category", ""),
                    )
                    print(f"    📷 Image trouvée ({source}): {image_url[:55]}...")
                    await asyncio.sleep(IMAGE_SEARCH_DELAY_SEC)

                # 3b. Embedding Mistral (sync SDK dans un thread + timeout / logs)
                try:
                    res = await traced_mistral_call(
                        "embeddings.create.seed",
                        asyncio.to_thread(
                            client.embeddings.create,
                            model="mistral-embed",
                            inputs=[item["description"]],
                        ),
                    )
                except MistralCallTimeoutError as e:
                    print(f"⚠️ Timeout Mistral sur {item['name']}: {e}")
                    continue
                vector = res.data[0].embedding

                # 4. size_guide : s'assurer que c'est un objet JSON (dict) valide
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

                # 5. Création de l'objet en base
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
                print(f"✅ {item['name']} ajouté à la file d'attente.")

            except Exception as e:
                print(f"⚠️ Erreur sur {item['name']}: {e}")

        await session.commit()
        print("\n✨ VICTOIRE ! Tout le catalogue est vectorisé et en base de données.")


if __name__ == "__main__":
    asyncio.run(seed())
