# Personal Shopper API

API FastAPI de **personal shopper** avec recherche sémantique (RAG), chat agentique et outils Mistral (embeddings, vision, audio Voxtral). Interface web sur **`/`**.

## Architecture

- **RAG** : les descriptions de vêtements sont vectorisées avec **Mistral Embed** et stockées dans **PostgreSQL + pgvector**. Le chat (`POST /chat`) récupère des candidats par similarité, le modèle répond en citant les **noms exacts** du catalogue ; la grille n’affiche que les articles **effectivement nommés** dans le texte de réponse.
- **Flux agentique** : le endpoint `/chat` injecte le contexte catalogue et le **profil** (mensurations, préférences). Modèle texte/vision par défaut : **`mistral-small-latest`** (`MISTRAL_CHAT_MODEL`). Embeddings : **`mistral-embed`** (`MISTRAL_EMBED_MODEL`). Transcription : **`voxtral-small-latest`** (`MISTRAL_TRANSCRIPTION_MODEL`).
- **Outils** : transcription (`/audio/transcribe`), extraction de guide tailles (`/size-extract`), conseil taille (`/chat/size-advice`), recherche (`/search`), panier, auth JWT.

## Stack technique

| Composant | Rôle |
|-----------|------|
| **Mistral AI** | Embeddings, chat, vision, transcription (Voxtral Small) |
| **FastAPI** | API HTTP async, validation Pydantic |
| **PostgreSQL + pgvector** | Données + vecteurs |
| **Alembic** | Migrations |
| **Docker Compose** | Services `db` + `app`, réseau `internal`, volumes, healthchecks |

## Lancement (Docker) — procédure actuelle

### Prérequis

- [Docker](https://docs.docker.com/get-docker/) et Docker Compose v2  
- Fichier **`.env`** à la racine (voir `.env.example`)

### 1. Configuration

```bash
cp .env.example .env
```

Renseigner au minimum :

- **`MISTRAL_API_KEY`** — obligatoire pour RAG, seed, chat, transcription, etc.
- Les variables **`DATABASE_*`** sont surchargées par Compose pour le service `app` (`DATABASE_HOST=db`). Gardez-les cohérentes avec le service **`db`** (utilisateur, mot de passe, nom de base).  
- Optionnel : **`DATABASE_URL`** (prioritaire sur les champs `DATABASE_*` si défini) — sous Docker, l’hôte Postgres doit être **`db`**, pas `localhost`.

Autres variables utiles : `MISTRAL_CHAT_MODEL`, `MISTRAL_EMBED_MODEL`, `MISTRAL_TRANSCRIPTION_MODEL`, `MISTRAL_HTTP_TIMEOUT_SECONDS`, `MISTRAL_RAG_MAX_TOKENS`, `JWT_SECRET`, **`APP_PORT`** (voir ci-dessous).

### 2. Démarrer la stack

```bash
docker compose up --build
```

- **API + UI** : `http://localhost:<port>` avec `<port>` = valeur de **`APP_PORT`** dans `.env` (défaut **8000**), ex. [http://localhost:8000](http://localhost:8000)  
- Au premier démarrage du conteneur **`app`**, le script **`scripts/start.sh`** enchaîne :
  1. `alembic upgrade head`
  2. `python -m scripts.seed_db` (idempotent)
  3. `uvicorn app.main:app --host 0.0.0.0 --port 8000`

**Seed** : si la table `garments` est **vide** → import de `app/data/catalog.json` (embeddings Mistral + images DuckDuckGo scorées si pas d’`image_url` dans le JSON). Si des lignes existent mais **`embedding` est NULL** → recalcul des embeddings uniquement. Si tout est à jour → message `Database already seeded. Skipping...`.

### 3. Variantes utiles

| Besoin | Commande |
|--------|----------|
| Premier build sans cache | `docker compose build --no-cache app` puis `docker compose up` |
| Tourner en arrière-plan | `docker compose up --build -d` |
| Arrêter | `docker compose down` |
| **Port 8000 déjà utilisé** | Dans `.env` : `APP_PORT=8001` puis `docker compose up --build` |
| Dev : code monté + reload | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build` |
| Seed manuel | `docker compose run --rm app python -m scripts.seed_db` |

### 4. Repartir sur un catalogue / base neuve

Le seed **ne duplique pas** les vêtements si la table est déjà remplie. Pour **tout réimporter** (nouveau `catalog.json`, nouvelles images, etc.) :

```bash
docker compose down -v
docker compose up --build
```

`-v` supprime le volume Postgres (**données effacées**).

Sans tout détruire, vous pouvez vider uniquement les articles (à exécuter selon votre user/base) :

```bash
docker compose exec db psql -U postgres -d personal_shopper -c "TRUNCATE garments RESTART IDENTITY CASCADE;"
docker compose restart app
```

(adaptez `personal_shopper` / utilisateur si besoin)

## Tutoriel d'utilisation

L’interface s’appelle **Carnet** ; elle est servie sur la racine du serveur (`/`). La doc interactive OpenAPI est sur [`/docs`](http://localhost:8000/docs) (adapter le port si `APP_PORT` ≠ 8000).

### 1. Première visite

1. Ouvrez l’URL de l’app (ex. `http://localhost:8000`).
2. Le bandeau de statut en haut à droite indique si l’API répond (`GET /health`).

Vous pouvez **poser une question au chat sans compte** : le conseiller utilise le catalogue RAG. En revanche, **sans connexion** vous n’avez pas de profil (mensurations, couleurs évitées, etc.) et pas de **panier** persistant.

### 2. Compte (connexion / inscription)

1. Cliquez sur **Connexion** dans la barre du haut.
2. Onglet **Inscription** : email + mot de passe (**minimum 8 caractères**).
3. Après inscription ou connexion, un **JWT** est stocké dans le navigateur (`localStorage`) ; les requêtes suivantes l’envoient automatiquement.

Pour vous déconnecter, utilisez l’action prévue dans l’UI (le token est alors retiré du stockage local).

### 3. Mensurations et profil

Pour des conseils plus fiables (chat morphologique, **conseil taille**), renseignez au minimum **tour de poitrine, tour de taille et tour de hanches** (cm) dans le profil.

- Après la **première** connexion ou inscription, une **modale** peut proposer de compléter ces mesures ; vous pouvez aussi y accéder via **Profil**.
- Tant que ces trois mesures ne sont pas remplies, un **bandeau** ou des **rappels** (chat, indicateur sur l’icône profil) peuvent vous le signaler.

Dans le profil, vous pouvez aussi indiquer prénom, tailles habituelles, style, couleurs à éviter, etc. Ces informations sont injectées dans le prompt du chat lorsque vous êtes connecté.

### 4. Conseiller style (chat)

1. Saisissez votre demande en langage naturel (ex. « Je cherche un pantalon noir pour le bureau »).
2. Le modèle répond de façon **courte** et ne doit citer que des articles **présents dans le catalogue**.
3. **Important pour la grille** : seuls les vêtements dont le **nom complet exact** apparaît dans le texte de la réponse sont listés en fiches sous le chat (boutons « Articles cités »). Si le modèle reformule ou abrège un titre, la fiche peut ne pas s’afficher — reformulez ou demandez de recopier le nom tel que dans le catalogue.

Les **filtres** (genre, fourchette de prix) au-dessus de la grille s’appliquent **aux articles déjà proposés** par le dernier message du conseiller (filtrage côté interface). Pour forcer genre / prix dès la recherche vectorielle, utilisez l’API `POST /chat` avec le corps JSON `price_min`, `price_max`, `gender` (voir `/docs`).

### 5. Voix (dictée)

À côté du champ de chat (et dans la fenêtre **conseil taille**), un bouton **micro** lance la capture audio (navigateurs type **Chrome / Edge** recommandés). L’audio est envoyé par morceaux à **`POST /audio/transcribe`** (Mistral / Voxtral) ; le texte transcrit remplit le champ — vous pouvez l’éditer puis envoyer comme un message classique. **Recliquer sur le micro** arrête l’enregistrement.

### 6. Fiches article, conseil taille, panier

- En cliquant sur un article cité ou sur une carte produit, vous ouvrez le détail (image, infos, guide des tailles si disponible).
- **Conseil taille** : dialogue dédié (`POST /chat/size-advice`) ; l’agent peut proposer une taille et, le cas échéant, **ajouter la ligne au panier** (compte requis).
- **Panier** : icône sac en haut à droite. Ajout / mise à jour des quantités nécessite d’être **connecté** (`/cart`, `/cart/items`).

### 7. API sans l’interface web

| Besoin | Endpoint (résumé) |
|--------|-------------------|
| Santé | `GET /health` |
| Recherche sémantique brute | `GET /search?q=...` (+ filtres optionnels `gender`, `price_min`, `price_max`) |
| Détail par nom | `GET /search/garment?name=...` |
| Chat RAG | `POST /chat` — header optionnel `Authorization: Bearer <token>` |
| Transcription | `POST /audio/transcribe` (fichier audio) |
| Guide tailles depuis une image PDF / visuel | `POST /size-extract` (fichier) |

Référence complète des schémas et exemples : **`/docs`**.

## Fonctionnalités agentiques (rappel)

Le flux reste **déterministe** dans le code (pas d’orchestrateur type LangGraph). Le profil JWT + `/profile` (dont **mensurations complètes** pour le conseil taille) enrichit le chat ; les outils HTTP peuvent être enchaînés côté client.

## Résilience & erreurs Mistral

| Sujet | Détail |
|--------|--------|
| Timeouts | `MISTRAL_HTTP_TIMEOUT_SECONDS`, `traced_mistral_call`, réponses **504** possibles |
| **429 / capacité** (`service_tier_capacity_exceeded`, etc.) | Côté **Mistral** (quota, plan, saturation). Messages utilisateur adoucis dans l’API ; consulter [console.mistral.ai](https://console.mistral.ai) |
| DB | Timeouts `asyncpg` via `DATABASE_CONNECT_TIMEOUT_*` |
| Santé | `depends_on` + healthcheck Postgres ; healthcheck `GET /health` sur `app` |

## Licence

À définir.
