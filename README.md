# Personal Shopper API

API FastAPI de **personal shopper** avec recherche sémantique (RAG), chat agentique et outils Mistral (embeddings, vision Pixtral, audio Voxtral).

## Architecture

- **RAG** : les descriptions de vêtements sont vectorisées avec **Mistral Embed** et stockées dans **PostgreSQL + pgvector**. La recherche `/search` calcule l’embedding de la requête et renvoie les articles les plus proches (similarité cosinus).
- **Flux agentique** : le endpoint `/chat` enrichit le prompt avec le contexte issu du catalogue (garments pertinents) et du profil utilisateur (mensurations, préférences). Le modèle de chat (**Mistral Large** ou équivalent configurable) produit des réponses contextualisées.
- **Outils / intégrations** :
  - **Transcription** (`/audio/transcribe`) : Voxtral pour du texte à partir d’audio.
  - **Extraction de guide tailles** (`/size-extract`) : Pixtral lit une image de tableau de tailles et renvoie un JSON structuré (poitrine, taille, hanches par taille).
  - **Conseil taille** : comparaison des mensurations utilisateur avec les `size_guide` des articles (logique métier côté service).

## Stack technique

| Composant | Rôle |
|-----------|------|
| **Mistral AI** | Embeddings, chat, vision (Pixtral), transcription (Voxtral) |
| **FastAPI** | API HTTP async, validation Pydantic |
| **PostgreSQL + pgvector** | Données relationnelles + vecteurs |
| **Alembic** | Migrations de schéma |
| **Docker / Compose** | Image multi-stage, DB + app, healthchecks, réseau interne |

## Démarrage rapide

1. **Cloner** le dépôt et se placer à la racine du projet.

2. **Configurer l’environnement** : copier `.env.example` vers `.env`, renseigner au minimum `MISTRAL_API_KEY` et les variables PostgreSQL (ou une `DATABASE_URL` async `postgresql+asyncpg://...`).

3. **Lancer la stack** :

   ```bash
   docker compose up --build
   ```

   L’API est disponible sur [http://localhost:8000](http://localhost:8000) (port modifiable via `APP_PORT`). Au démarrage du conteneur `app`, **`alembic upgrade head`** est exécuté automatiquement (`scripts/start.sh`).

**Seed du catalogue de démo** (si la table des vêtements est vide, avec appels Mistral pour les embeddings) :

```bash
docker compose run --rm app python scripts/seed_db.py
```

**Mode développement** (code monté + `--reload`) :

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

## Fonctionnalités agentiques

L’agent ne remplace pas une orchestration type LangGraph : le **flux est déterministe** dans le code (FastAPI + services). En pratique :

- Les **mensurations** et le **profil** (JWT + `/profile`) sont injectés dans le prompt du chat pour des recommandations adaptées.
- Les **outils** exposés en HTTP (recherche, panier, transcription, extraction tableau de tailles) peuvent être enchaînés côté client ou UI ; le backend fournit des briques spécialisées plutôt qu’un planner autonome multi-étapes.

## Résilience (points de défaillance uniques traités)

| Risque | Mitigation dans le projet |
|--------|---------------------------|
| Appels Mistral sans limite de temps | `traced_mistral_call` + `MISTRAL_HTTP_TIMEOUT_SECONDS` (asyncio `wait_for`), logs `mistral_ok` / `mistral_timeout` / `mistral_error`. |
| API HTTP bloquée → routes qui pendent | Erreur **504** sur les routes concernées en cas de timeout Mistral. |
| Connexion / requêtes DB sans timeout | `asyncpg` : `timeout` et `command_timeout` via `DATABASE_CONNECT_TIMEOUT_SECONDS` et `DATABASE_COMMAND_TIMEOUT_SECONDS`. |
| Migrations oubliées au déploiement | `scripts/start.sh` exécute `alembic upgrade head` avant Uvicorn. |
| Healthchecks | Postgres (`pg_isready`) avant le démarrage de `app` ; `GET /health` pour le conteneur applicatif. |

Pistes supplémentaires pour la prod : file d’attente pour les appels Mistral, budgets de coût, circuit breaker, réplication PostgreSQL, secrets via un gestionnaire dédié (Vault, SSM, etc.).

## Licence

À définir selon votre politique de dépôt.
