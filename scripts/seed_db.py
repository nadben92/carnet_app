#!/usr/bin/env python3
"""
Seed du catalogue de démonstration (embeddings Mistral) si la table garments est vide.

Usage (racine du dépôt) :
  python scripts/seed_db.py

Avec Docker :
  docker compose run --rm app python scripts/seed_db.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.scripts.seed_db import seed as run_seed  # noqa: E402


def main() -> None:
    asyncio.run(run_seed())


if __name__ == "__main__":
    main()
