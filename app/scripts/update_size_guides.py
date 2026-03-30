"""Met à jour les size_guide des vêtements existants depuis le catalogue JSON."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.getcwd())

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession

from app.core.config import get_settings
from app.models.garment import Garment


async def update_size_guides() -> None:
    """Met à jour size_guide pour chaque vêtement dont le nom existe dans le catalogue."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    data_path = os.path.join("app", "data", "catalog.json")
    if not os.path.exists(data_path):
        print(f"❌ Fichier {data_path} introuvable.")
        return

    with open(data_path, encoding="utf-8") as f:
        catalog = json.load(f)

    catalog_by_name = {item["name"]: item.get("size_guide") for item in catalog if item.get("size_guide")}

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Garment))
        garments = result.scalars().all()
        updated = 0
        for g in garments:
            if g.name in catalog_by_name:
                g.size_guide = catalog_by_name[g.name]
                updated += 1
                print(f"✅ {g.name} : size_guide mis à jour")
        await session.commit()
        print(f"\n✨ {updated}/{len(garments)} vêtements mis à jour.")


if __name__ == "__main__":
    asyncio.run(update_size_guides())
