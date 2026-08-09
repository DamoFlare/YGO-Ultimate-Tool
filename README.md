# 🎴 Yu-Gi-Oh! TCG Valuer & Collection Tracker (Web App)

Welcome to **Yu-Gi-Oh! TCG Valuer & Collection Tracker**, a local web application built in Python. This tool lets you manage your Yu-Gi-Oh! card collection, search for cards in real time through the official **YGOPRODeck** API, and instantly value them using **real, live marketplace listing prices from CardTrader** — not an aggregated or historical estimate.

It's a single-user, local-only tool: a small [FastAPI](https://fastapi.tiangolo.com/) server runs on your machine and serves the UI in your browser at `http://127.0.0.1:8000`. It was originally built as a terminal (TUI) app; it was rebuilt as a local web app because the Grading module's image display genuinely needs a browser to render/scale photos reliably (see `.CLAUDE/06-notes-and-discrepancies.md` for the story).

---

## ✨ Key Features

1. **Advanced Search & Normalization**:
   - Enter a card name in **Italian** or **English** (with fuzzy matching support). The app queries the **YGOPRODeck** API and returns the official, normalized English name — this API is used only for card lookup, never for pricing.
   - Direct lookup by **Set Code** (e.g. `RA01-EN001` or `LOB-001`) or by **Passcode (card ID)** is also supported.
2. **Real Marketplace Pricing via CardTrader**:
   - Every price shown comes from **CardTrader**'s live marketplace listings (real sellers, real stock), matched by set code and rarity — not a cached/aggregated estimate.
   - For each condition (NM/EX/GD/LP/PO) the app looks for the lowest **actually listed** price in that exact condition. If a specific condition currently has no active listing, it's estimated from the real NM price using standard condition multipliers (NM 100%, EX 88%, GD 72.5%, LP 55%, PO 35%) as a fallback only.
   - Real-time automatic calculation of the total collection portfolio value, both in NM condition and for the other conditions.
3. **Persistence & CSV Export**:
   - Automatic data saving in a local **SQLite** database (`collection.db`).
   - Professional CSV export (`collection.csv`) with detailed columns for every condition, including the grade and the effective condition detected by the Grading module.
4. **Bulk Add**:
   - Paste multiple set codes at once and confirm them one by one before the final save to the collection.
5. **Hybrid CV + Local AI Automatic Grading**:
   - Analyzes a photo of a physical card and computes an objective **1-10** grade, PSA/BGS style, combining:
     - **Deterministic Computer Vision** (OpenCV) for measurable geometric defects — edge wear and centering.
     - **A local Vision-Language model** (Ollama + `llava`, self-hosted via Docker, no data ever leaves your machine) for surface defects — scratches and creases.
   - Shows your uploaded photo side by side with the normalized/cropped image with the actual analysis overlaid (yellow band = perimeter checked for wear, red pixels = spots actually flagged as worn, cyan rectangle = detected centering frame), plus a plain-language explanation of *why* that grade was reached.
   - The grade is mapped onto the existing NM/EX/GD/LP/PO condition scale, so you can compare your copy's "real" value against the theoretical NM value already shown in the collection.
   - Known limitation: unlike real PSA/BGS grading, it does not compute a separate Corners subgrade. Details in `.CLAUDE/07-grading.md`.
6. **Sell on CardTrader (bulk or single card)**:
   - Select one or more cards from your collection and review them on a dedicated page before creating real listings on CardTrader via its Full API.
   - Each row shows the CardTrader printing's own photo (resolved automatically from set code + rarity) so you can visually catch a wrong match before confirming — a wrong match here means promising a buyer the wrong physical card.
   - Condition and language are always chosen explicitly per card (never silently assumed), with an auto-suggested price (the app's own displayed value minus a configurable discount) that stays fully editable.
   - Manage active listings from the same page: cancel a listing, manually check for sales (CardTrader has no webhooks), or push updated prices to already-live listings.
7. **Built-in Rate Limiting**:
   - Asynchronous handling of both YGOPRODeck's and CardTrader's API limits (controlled delays between requests) to avoid hitting either provider's rate caps.

---

## 🛠 System Requirements & Installation

Requires **Python 3.10 or higher**. Designed to run entirely inside an isolated virtual environment.

### 1. Set up the virtual environment and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure your CardTrader API token (required for pricing)
All prices shown by the app come from [CardTrader](https://www.cardtrader.com)'s real marketplace API. Get a Bearer token from your CardTrader profile settings, then create a `.env` file in the project root (copy `.env.example`) with:

```
CARDTRADER_TOKEN=your-token-here
```

`.env` is git-ignored — your token never gets committed, and it's read only by the local server, never sent to the browser. Without a valid token, card search still works, but no pricing will be available (the app fails gracefully, showing `€0.00` rather than crashing).

### 3. Start the local Vision model (only required by the Grading tab)
The Grading module relies on a self-hosted **Ollama** server running the `llava` model, included in this repository as a Docker Compose setup — no external API key needed, no data ever leaves your machine:

```bash
docker compose up -d
```

On the first run, the container automatically downloads the `llava` model (a few GB, this can take a few minutes); on subsequent restarts the model stays cached in the Docker volume and startup is instant. The API is exposed on `http://localhost:11434`. If you don't need to grade cards in this session, you can skip this step: the rest of the app works fine without it.

---

## 🚀 Running the Application

```bash
python main.py
```

This starts the server on `http://127.0.0.1:8000` — open that URL in your browser. Press `Ctrl+C` in the terminal to stop it.

⚠️ The server binds to `127.0.0.1` (localhost) only, by design — never expose it to the network. It holds your CardTrader token and reads/writes your local collection database.

### Navigating the app
The interface has 5 pages, navigable from the top bar:

#### 1. 📋 `Collection & Valuation`
The main dashboard.
- **Card Table**: Lists all your saved cards, showing passcode ID, Name, Set Code, Rarity, Quantity, NM Price, and estimates for all lower conditions (EX, GD, LP, PO), plus the grade and the effective real-world value when a card has been graded. Click a column header to sort. Rows are highlighted when a card is currently for sale or already sold.
- **Metrics Bar**: Number of unique cards, total pieces, and total NM value in euros.
- **Condition Breakdown Bar**: Estimated total value if the whole collection were in Excellent, Good, Light Played, or Poor condition.
- **Live Filter**: Type in the search box to instantly filter by name or set code (updates as you type).
- **Refresh Prices**: Re-queries CardTrader for every card's current real marketplace price.
- **Export CSV**: Downloads a detailed report as `collection.csv`.
- **Sell**: Select cards via checkboxes (or a single card's own button) to send them to the Sell page for review.
- **Delete**: Remove a card from the collection (blocked while the card has an active CardTrader listing).

#### 2. ➕ `Add Card`
- **Search**: Italian name (`Mago Nero`), English name (`Dark Magician`), a set code (`RA01-EN001`), or a numeric passcode (`46986414`).
- Every matching card is shown with **all of its printings/sets already listed underneath** — pick the exact one you own and set the quantity, then click "Add". The real CardTrader price is looked up only at that point (no price is shown before you confirm).

#### 3. 🚀 `Bulk Add`
For adding many cards at once (e.g. after a big purchase/trade).
- Paste multiple set codes separated by spaces or newlines (e.g. `RA01-EN001 LOB-001 SDMM-IT014`) and click "Load Codes".
- For each card in the queue, pick the correct printing and confirm, or skip it — one at a time.
- Once the queue is done, click "Save All to Collection" to persist everything to disk.

#### 4. 🩺 `Card Grading (CV + AI)`
- Upload a photo of the physical card and click "Analyze Card".
- You'll see your original photo next to the normalized/analyzed version with the CV overlays, the Centering/Edges/Surface subgrades, the final 1-10 grade, the mapped condition, a plain-language explanation of why that grade was reached, and what the AI observed on the card's surface.
- To save the result, search for the matching card below, pick the set/rarity, and click "Save with Grade": a new entry is created in the collection with the grade applied, so you can compare its real value against the theoretical NM estimate in the Collection page.

#### 5. 💰 `Sell on CardTrader`
- Cards sent here from the Collection page appear in a review table: each row shows the resolved CardTrader printing's photo, and lets you pick language, condition, price, and quantity before confirming.
- If the automatic match is ambiguous, you pick the correct printing yourself from the candidates shown (with their photos) — that choice is remembered for that card going forward.
- Once confirmed, real listings are created on CardTrader. A second table lists all your listings (active, sold, cancelled) with actions to cancel a listing, manually check for new sales, or sync an active listing's price to the collection's current value.

---

## 📁 Codebase Directory Structure

```text
YGO-Ultimate-Tool/
│
├── .venv/                  # Python virtual environment
├── .env                    # Local secrets (CARDTRADER_TOKEN) — git-ignored, copy from .env.example
├── docker-compose.yml      # Self-hosted Ollama server (llava model) for the Grading module
├── docker/
│   ├── Dockerfile
│   └── ollama-entrypoint.sh
├── config.py               # Configuration: web host/port, condition multipliers, grading thresholds
├── models.py                # Pydantic data classes (Card, Prices, CollectionItem, Listing, GradingResult)
├── main.py                  # Entry point — starts the uvicorn/FastAPI server
├── requirements.txt         # External dependencies
├── collection.db           # Local SQLite database (auto-generated) — collection + CardTrader listings
├── collection.csv          # Spreadsheet export (auto-generated)
├── scripts/
│   └── migrate_to_sqlite.py  # One-off migration from a legacy collection.json into collection.db
│
├── services/
│   ├── ygoprodeck_api.py    # Async HTTP client for the YGOPRODeck API (card search only, no pricing)
│   ├── cardtrader_api.py    # Async client for CardTrader's real marketplace prices + listing management
│   ├── storage.py           # SQLite persistence for the collection, listings, and CSV export
│   └── grading/
│       ├── geometric_agent.py  # Deterministic CV: normalization, edge wear, centering
│       ├── ai_agent.py         # Async client to Ollama (VLM `llava`) for surface analysis
│       └── grader.py           # Orchestrator: merges both agents into the final 1-10 grade
│
└── web/                     # FastAPI web application (UI layer)
    ├── app.py                # FastAPI app + lifespan (starts/stops the shared services)
    ├── state.py              # Shared in-memory app state (collection, API clients, active flows)
    ├── deps.py                # Shared dependencies: templates, access to the app state
    ├── routers/
    │   ├── collection.py      # Collection page + table filter/sort/refresh/delete/export
    │   ├── add_card.py        # Add Card search + confirm
    │   ├── bulk_add.py        # Bulk Add queue flow
    │   ├── grading.py         # Photo upload, analysis, link-to-collection
    │   └── sell.py            # Sell on CardTrader: staging/review, listing creation and management
    ├── templates/            # Jinja2 HTML templates (one page + partials per section)
    └── static/
        ├── htmx.min.js        # Vendorized htmx (no CDN, no build step)
        ├── corner-picker.js   # Vanilla JS manual card cropper for the Grading page
        ├── sell.js            # Vanilla JS: auto-fills the suggested price on the Sell page
        └── style.css          # Hand-written dark theme
```

---

## 🔒 Rate Limiting and Security
The application follows both providers' rate limits: an asynchronous `0.05`-second pause between YGOPRODeck requests, and a `0.1`-second pause between CardTrader requests (CardTrader's real limit is 200 requests/10s globally, 10 req/s on the marketplace endpoint). Do not lower these values, to avoid a temporary ban of your IP address or API token.

The web server binds to `127.0.0.1` only and has no authentication — this is intentional for a single-user local tool holding a live API token, **never** change the bind host to `0.0.0.0` or expose this port to the internet.
