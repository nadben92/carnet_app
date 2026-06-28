# Carnet — AI-Native Fashion Commerce

**Carnet** is a reference implementation of what an online clothing store should look like when AI is woven into every layer of the experience — not as a chatbot bolt-on, but as the core product.

Instead of browsing endless grids and guessing sizes, shoppers describe what they want in natural language, speak their intent, and receive grounded recommendations from a catalog the system actually understands. Fit advice is personalized to body measurements. Size guides can be extracted from images. The entire flow — discovery, consultation, sizing, and cart — is designed around human conversation augmented by deterministic, traceable AI tooling.

This project demonstrates that vision end-to-end: a production-ready FastAPI backend, a web interface served at `/`, and a full Mistral AI stack (embeddings, chat, vision, voice).

---

## What makes it AI-first

| Capability | How it works |
|------------|--------------|
| **Semantic discovery** | Garment descriptions are embedded with **Mistral Embed** and stored in **PostgreSQL + pgvector**. The stylist chat retrieves candidates by cosine similarity, then responds citing **exact catalog names** — the UI only surfaces products genuinely referenced in the answer. |
| **Profile-aware styling** | Logged-in users inject measurements, preferred sizes, style notes, and color avoidances into every chat turn. Recommendations adapt to the person, not just the query. |
| **Voice input** | Browser microphone capture is transcribed via **Voxtral** (`POST /audio/transcribe`), enabling hands-free shopping queries. |
| **Vision-powered sizing** | Upload a size-chart image or PDF and the system extracts structured size guides (`POST /size-extract`) using Mistral vision. |
| **Fit advisor agent** | A dedicated sizing dialogue (`POST /chat/size-advice`) compares user measurements against garment size guides, recommends a size, and can add the item to cart on explicit request. |
| **Deterministic orchestration** | Agentic flows are implemented in application code — no opaque orchestration framework. Every Mistral call is traced, timeout-bounded, and mapped to clear HTTP responses. |

---

## Architecture

```
Shopper (web UI)
      │
      ▼
FastAPI  ──►  JWT auth · profile · cart
      │
      ├── RAG retrieval (pgvector + Mistral Embed)
      ├── Chat / fit advisor (mistral-small-latest)
      ├── Size extraction (vision)
      └── Transcription (voxtral-small-latest)
      │
      ▼
PostgreSQL  (catalog, embeddings, users, cart)
```

**Default models** (overridable via `.env`):

- Chat, RAG, fit advisor, vision: `mistral-small-latest`
- Embeddings: `mistral-embed`
- Transcription: `voxtral-small-latest`

---

## Tech stack

| Layer | Choice |
|-------|--------|
| AI | [Mistral AI](https://mistral.ai) — embeddings, chat, vision, Voxtral |
| API | FastAPI, Pydantic v2, async SQLAlchemy 2.0 |
| Data | PostgreSQL + pgvector |
| Migrations | Alembic |
| Runtime | Docker Compose (multi-stage image, healthchecks) |

---

## Quick start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2
- A `.env` file at the project root (see `.env.example`)

### 1. Configure environment

```bash
cp .env.example .env
```

Required:

- **`MISTRAL_API_KEY`** — powers RAG, chat, seeding, transcription, and vision
- **`DATABASE_*`** — overridden by Compose for the `app` service (`DATABASE_HOST=db`). Keep credentials aligned with the `db` service.

Optional: `MISTRAL_CHAT_MODEL`, `MISTRAL_EMBED_MODEL`, `MISTRAL_TRANSCRIPTION_MODEL`, `MISTRAL_HTTP_TIMEOUT_SECONDS`, `MISTRAL_RAG_MAX_TOKENS`, `JWT_SECRET`, `APP_PORT` (default **8000**).

### 2. Launch

```bash
docker compose up --build
```

Open **http://localhost:8000** (or your `APP_PORT`). On first boot, `scripts/start.sh` runs migrations, seeds the catalog, and starts Uvicorn.

**Seeding behavior:**

- Empty `garments` table → imports `app/data/catalog.json` with Mistral embeddings (and DuckDuckGo-scored images when `image_url` is missing)
- Rows with `NULL` embeddings → recomputes embeddings only
- Already seeded → skips with `Database already seeded. Skipping...`

### 3. Common commands

| Task | Command |
|------|---------|
| Clean rebuild | `docker compose build --no-cache app && docker compose up` |
| Run detached | `docker compose up --build -d` |
| Stop | `docker compose down` |
| Port conflict | Set `APP_PORT=8001` in `.env`, then `docker compose up --build` |
| Dev (hot reload) | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build` |
| Manual seed | `docker compose run --rm app python -m scripts.seed_db` |

### 4. Reset catalog / database

To fully re-import (new catalog, fresh embeddings):

```bash
docker compose down -v
docker compose up --build
```

`-v` destroys the Postgres volume. To truncate garments only:

```bash
docker compose exec db psql -U postgres -d personal_shopper -c "TRUNCATE garments RESTART IDENTITY CASCADE;"
docker compose restart app
```

---

## Using Carnet

The web UI is served at `/`. Interactive API docs: [`/docs`](http://localhost:8000/docs).

### Browse without an account

Anyone can chat with the AI stylist — RAG runs against the full catalog. Without login, there is no persistent profile or cart.

### Create an account

Sign up with email and password (8+ characters). A JWT is stored in `localStorage` and attached to subsequent requests.

### Complete your profile

For reliable fit advice, enter **chest, waist, and hip measurements** (cm). A modal prompts new users; a banner reminds you until all three are filled. Optional fields — name, usual sizes, style preferences, colors to avoid — enrich chat context.

### Chat with the stylist

Describe what you need in plain language (e.g. *"I'm looking for a black office trouser"*). The model responds concisely and cites only in-catalog items. Product cards appear **only when the exact garment name appears in the response** — if a title is paraphrased, ask the stylist to repeat the catalog name.

Gender and price filters above the grid apply to items from the latest reply. To filter at retrieval time, pass `gender`, `price_min`, and `price_max` in the `POST /chat` body.

### Voice input

Click the microphone next to the chat field (Chrome / Edge recommended). Audio is streamed to `POST /audio/transcribe`; the transcribed text fills the input for editing before send. Click again to stop recording.

### Product detail, fit advice, cart

- Click a cited item or product card for details, images, and size guides.
- **Fit advice** opens a dedicated dialogue; the agent can recommend a size and add to cart on explicit request (login required).
- The bag icon manages cart items via `/cart` endpoints (login required).

---

## API overview

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness + database check |
| `GET /search?q=...` | Raw semantic search (`gender`, `price_min`, `price_max` optional) |
| `GET /search/garment?name=...` | Garment detail by name |
| `POST /chat` | RAG stylist chat — optional `Authorization: Bearer <token>` |
| `POST /chat/size-advice` | Fit advisor dialogue |
| `POST /audio/transcribe` | Audio → text (Voxtral) |
| `POST /size-extract` | Image/PDF → structured size guide |

Full schemas and examples: **`/docs`**.

---

## Resilience

| Topic | Detail |
|-------|--------|
| Timeouts | `MISTRAL_HTTP_TIMEOUT_SECONDS` via `traced_mistral_call`; API may return **504** |
| Rate limits | Mistral **429** / capacity errors surface user-friendly messages; check [console.mistral.ai](https://console.mistral.ai) |
| Database | `asyncpg` connect/command timeouts via `DATABASE_CONNECT_TIMEOUT_*` |
| Health | Postgres `depends_on` + healthcheck; app exposes `GET /health` |

