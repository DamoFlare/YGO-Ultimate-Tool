# 🎴 Yu-Gi-Oh! TCG Valuer & Collection Tracker (TUI)

Welcome to **Yu-Gi-Oh! TCG Valuer & Collection Tracker**, an advanced CLI application with a terminal user interface (**TUI**) built in Python. This tool lets you manage your Yu-Gi-Oh! card collection, search for cards in real time through the official **YGOPRODeck** API, and instantly value them using **real, live marketplace listing prices from CardTrader** — not an aggregated or historical estimate.

---

## ✨ Key Features

1. **Advanced Search & Normalization (Module 1)**:
   - Enter a card name in **Italian** or **English** (with fuzzy matching support). The app queries the **YGOPRODeck** API and returns the official, normalized English name — this API is used only for card lookup, never for pricing.
   - Direct lookup by **Set Code** (e.g. `RA01-EN001` or `LOB-001`) or by **Passcode (card ID)** is also supported.
2. **Real Marketplace Pricing via CardTrader (Module 2)**:
   - Every price shown comes from **CardTrader**'s live marketplace listings (real sellers, real stock), matched by set code and rarity — not a cached/aggregated estimate.
   - For each condition (NM/EX/GD/LP/PO) the app looks for the lowest **actually listed** price in that exact condition. If a specific condition currently has no active listing, it's estimated from the real NM price using standard condition multipliers (NM 100%, EX 88%, GD 72.5%, LP 55%, PO 35%) as a fallback only.
   - Real-time automatic calculation of the total collection portfolio value, both in NM condition and for the other conditions.
3. **Persistence & CSV Export**:
   - Automatic data saving in JSON format (`collection.json`).
   - Professional CSV export (`collection.csv`) with detailed columns for every condition, including the grade and the effective condition detected by the Grading module.
4. **Bulk Add**:
   - Paste multiple set codes at once and confirm them one by one before the final save to the collection.
5. **Hybrid CV + Local AI Automatic Grading (Module 3)**:
   - Analyzes a photo of a physical card and computes an objective **1-10** grade, PSA/BGS style, combining:
     - **Deterministic Computer Vision** (OpenCV) for measurable geometric defects — edge wear and centering.
     - **A local Vision-Language model** (Ollama + `llava`, self-hosted via Docker, no data ever leaves your machine) for surface defects — scratches and creases.
   - The grade is mapped onto the existing NM/EX/GD/LP/PO condition scale, so you can compare your copy's "real" value against the theoretical NM value already shown in the collection.
   - Known limitation: unlike real PSA/BGS grading, it does not compute a separate Corners subgrade. Details in `.CLAUDE/07-grading.md`.
6. **Built-in Rate Limiting**:
   - Asynchronous handling of both YGOPRODeck's and CardTrader's API limits (controlled delays between requests) to avoid hitting either provider's rate caps.

---

## 🛠 System Requirements & Installation

The application is designed to run entirely inside an isolated virtual environment (`.venv`) using **Python 3.10 or higher**.

### 1. Clone/enter the project folder
```bash
cd c:\Users\ferla\Desktop\YGO-TGC-Valuer
```

### 2. Set up the virtual environment and install dependencies
If you haven't already, create the environment and install the packages with the following commands:

```powershell
# Create the virtual environment
python -m venv .venv

# Install the required dependencies (textual, httpx, pydantic, opencv, ollama, ...)
.\.venv\Scripts\python -m pip install -r requirements.txt
```

### 3. Configure your CardTrader API token (required for pricing)
All prices shown by the app come from [CardTrader](https://www.cardtrader.com)'s real marketplace API. Get a Bearer token from your CardTrader profile settings, then create a `.env` file in the project root (copy `.env.example`) with:

```
CARDTRADER_TOKEN=your-token-here
```

`.env` is git-ignored — your token never gets committed. Without a valid token, card search still works, but no pricing will be available (the app fails gracefully, showing `€0.00` rather than crashing).

### 4. Start the local Vision model (only required by the Grading tab)
The Grading module relies on a self-hosted **Ollama** server running the `llava` model, included in this repository as a Docker Compose setup — no external API key needed, no data ever leaves your machine:

```bash
docker compose up -d
```

On the first run, the container automatically downloads the `llava` model (a few GB, this can take a few minutes); on subsequent restarts the model stays cached in the Docker volume and startup is instant. The API is exposed on `http://localhost:11434`. If you don't need to grade cards in this session, you can skip this step: the rest of the app works fine without it.

---

## 🚀 Using the Application (User Guide)

### Start the application:
```powershell
.\.venv\Scripts\python main.py
```

### Navigation and TUI Interface:
The interface is split into 4 main tabs, navigable by clicking the titles with the mouse or using the keyboard:

#### 1. 📋 `Collection & Valuation` tab
This is the main dashboard where your portfolio is displayed.
- **Card Table**: Lists all your saved cards, showing passcode ID, Name, Set Code, Rarity, Quantity, NM Price, and estimates for all lower conditions (EX, GD, LP, PO), plus the grade and the effective real-world value when a card has been graded.
- **Metrics Bar**: Shows at the top the number of unique cards, total pieces, and the total NM value in euros.
- **Condition Breakdown Bar**: Instantly displays the estimated total value if the whole collection were in Excellent, Good, Light Played, or Poor condition.
- **Real-Time Filter**: Type text into the search bar (`Filter collection...`) to instantly search your local list by name or set code.
- **Refresh Prices (🔄)**: Runs a background scan of the cards in your collection to fetch the latest real CardTrader marketplace prices.
- **Export CSV (📥)**: Saves a detailed, professional report to `collection.csv`.
- **Delete Selected (🗑️)**: Click a table row and press the button (or use the keyboard) to permanently remove a card from the database.

#### 2. ➕ `Add Card` tab
The panel dedicated to card lookup and normalization.
- **Search**: Type a search term in the top bar. You can enter:
  - The Italian name (e.g. `Mago Nero`, `Drago Bianco Occhi Blu`).
  - The English name (e.g. `Dark Magician`).
  - A specific set code (e.g. `RA01-EN001`).
  - A numeric passcode ID (e.g. `46986414`).
- **Card Selection**: Once you click `Search`, the left column `Cards Found` shows every match found in the YGOPRODeck database. Select the card you want.
- **Version / Rarity Selection**: The right column `Select Set / Version / Rarity` shows every historical printing of that card with its rarity. Select the exact printing you own — the real price is looked up from CardTrader only after you confirm (see below), so no price is shown at this stage.
- **Confirm and Add**: Specify the desired quantity (e.g. `3`) and click `Add to Collection`. The app looks up the real CardTrader price for that exact printing, then saves the card instantly to `collection.json`, updating your collection.

#### 3. 🚀 `Bulk Add` tab
For adding many cards at once (e.g. after a big purchase/trade).
- Paste multiple set codes into the text box, separated by spaces or newlines (e.g. `RA01-EN001 LOB-001 SDMM-IT014`).
- Press the load button: the app resolves each code via the API and queues them up.
- For each queued card, pick the correct version/rarity from the list and confirm (or skip the card if it's not the right one), advancing through the queue one at a time.
- When done, permanently save all confirmed cards to the collection.

#### 4. 🩺 `Card Grading (CV + AI)` tab
Computes an objective 1-10 grade from a photo of the physical card, combining CV and local AI.
- Enter the path to a local image file (e.g. `/photos/dark_magician.jpg`), or click `📂 Browse` to open a directory tree and pick the image file visually instead of typing the path. Then press `Analyze Card`.
- The app stays responsive while the analysis runs in the background (this requires the Ollama server to be running, see the Installation section); once done it shows the Centering/Edges/Surface subgrades, the final grade, and the mapped condition (NM/EX/GD/LP/PO).
- If you want to save the result, search for the matching card (same search engine as the Add Card tab), select the set/rarity, and press `Save with Grade to Collection`: a new entry is created in the collection with the grade and condition applied, so you can compare its real value against the theoretical NM estimate in the Collection tab.

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
├── config.py               # Configuration, condition multipliers, grading thresholds
├── models.py               # Pydantic data classes (Card, Prices, CollectionItem, GradingResult)
├── main.py                 # Program entry point
├── requirements.txt        # External dependencies
├── collection.json         # Local collection save file (auto-generated)
├── collection.csv          # Spreadsheet export (auto-generated)
│
├── services/
│   ├── ygoprodeck_api.py   # Async HTTP client for the YGOPRODeck API (card search only, no pricing)
│   ├── cardtrader_api.py   # Async client for CardTrader's real marketplace prices
│   ├── storage.py          # Persistence logic for JSON and CSV files
│   └── grading/
│       ├── geometric_agent.py  # Deterministic CV: normalization, edge wear, centering
│       ├── ai_agent.py         # Async client to Ollama (VLM `llava`) for surface analysis
│       └── grader.py           # Orchestrator: merges both agents into the final 1-10 grade
│
└── ui/
    ├── app.py              # Main Textual App class and inline CSS design
    ├── views/
    │   ├── collection_view.py # Collection table and statistics
    │   ├── add_card_view.py   # Search, autocomplete, and add-to-collection form logic
    │   ├── bulk_add_view.py    # Bulk insertion of multiple set codes
    │   └── grading_view.py     # Interface for the CV + AI Grading module
    └── screens/
        └── image_picker_screen.py  # "Browse" modal: filesystem directory tree to pick an image
```

---

## 🔒 Rate Limiting and Best Practices
The application follows both providers' rate limits: an asynchronous `0.05`-second pause between YGOPRODeck requests, and a `0.1`-second pause between CardTrader requests (CardTrader's real limit is 200 requests/10s globally, 10 req/s on the marketplace endpoint). Do not lower these values, to avoid a temporary ban of your IP address or API token.
