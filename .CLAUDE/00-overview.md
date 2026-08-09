# YGO Ultimate Tool — Overview

## What it is

Local web application (Python, FastAPI + server-side HTML with htmx) to manage and value a
collection of Yu-Gi-Oh! TCG cards. Descriptive name in the README: "Yu-Gi-Oh! TCG Valuer &
Collection Tracker". The historical/project folder was `YGO-TGC-Valuer/`.

A local server (`python main.py`) exposes the interface in the browser at
`http://127.0.0.1:8000` — single-user, bound only to localhost, no authentication (not
needed: no one other than the machine's owner can reach it). **It was originally a
Textual TUI**: it was retired and rebuilt as a web app because the Grading module needed
to reliably display photos, something that terminal graphics rendering did not
guarantee (two non-trivial library bugs, see [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md)).

GitHub repository: `DamoFlare/YGO-Ultimate-Tool` (remote `origin`), single branch `main`.

## What it does (in brief)

1. Searches for cards (by name, by passcode/numeric ID, or by set code like `RA01-EN001`) via
   the public **YGOPRODeck** API — used only to identify the card, never for prices.
2. Adds the cards found to a personal collection, with quantity and actual price.
3. Calculates the collection's value using **real market prices from CardTrader**
   (live listings, not aggregated/historical) for each condition (NM/EX/GD/LP/PO), with a
   multiplier-based estimate only as a fallback when there is no real listing for that condition.
   See [08-cardtrader-pricing.md](08-cardtrader-pricing.md).
4. Persists the collection in **SQLite** (`collection.db`) and exports on request to
   `collection.csv`. `collection.json` is now only a historical pre-migration backup, no longer
   read nor written by the app — see [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md).
5. Offers a bulk-entry mode ("Bulk Add") to paste many set codes at once and confirm them
   one by one.
6. **Automatically grades** a physical card from a photo: a hybrid CV (OpenCV,
   deterministic) + local VLM (Ollama/`llava`, self-hosted via Docker) architecture calculates a
   1-10 grade in PSA/BGS style and maps it to the existing NM/EX/GD/LP/PO condition. See
   [07-grading.md](07-grading.md). It replaced the previous placeholder OCR scanner.
7. **Sells cards on CardTrader** (bulk or single): selects cards from the collection, reviews
   condition/price/quantity on a dedicated page (with a photo of the exact printing resolved on
   CardTrader for an anti-mismatch visual check), confirms to create real listings via
   `POST /products`. No automatic sale synchronization (no CardTrader
   webhook) — status is updated only with a manual check. See
   [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md).

## Project status

- Young repository: started from 2 initial commits (`First commit`, then `Update .gitignore and
  add pyvenv configuration file`), then Textual TUI → Grading module (CV+VLM) → price
  migration to CardTrader → complete migration from TUI to web app (FastAPI + htmx) → collection
  persistence migration from JSON to SQLite → **card-selling feature on CardTrader** (bulk +
  single, same session as the SQLite migration, done on purpose to give it a stable `row_id` —
  see [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md)).
- The selling feature required a live test with immediate creation/deletion of a
  real listing (explicitly confirmed by the user before proceeding) to discover two
  real deviations from CardTrader's official documentation (product id nested in
  `resource.id`, language property called `yugioh_language` instead of `language`) — see
  [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md) for details, useful before further
  modifying `services/cardtrader_api.py::create_listing`.
- No "formal" automated tests (no `pytest`/`tests/`), but every feature was verified
  end-to-end with real calls to external services (YGOPRODeck, CardTrader, Ollama) during
  development. No CI/CD, no declared license.
- The README describes the 4 pages (Collection, Add Card, Bulk Add, Card Grading) as
  web pages, no longer tabs of a TUI.
- The Grading module requires a local Ollama server running (`docker compose up -d`,
  see [01-stack-and-setup.md](01-stack-and-setup.md)) — without it, the Grading page fails with a
  clear error but the other pages work normally.
- Pricing requires a valid CardTrader token in `.env` (`CARDTRADER_TOKEN`) — without it,
  card search still works but no price is ever shown (silent fallback to
  `€0.00`). See [08-cardtrader-pricing.md](08-cardtrader-pricing.md).

## Knowledge base index

- [01-stack-and-setup.md](01-stack-and-setup.md) — language, dependencies, how to start the project
  (Docker for Ollama, CardTrader token)
- [02-architecture.md](02-architecture.md) — layered structure, entry point, request flow
- [03-data-models.md](03-data-models.md) — `config.py`, `models.py`, JSON/CSV formats
- [04-services.md](04-services.md) — `services/` (search/price API client, storage, grading)
- [05-ui.md](05-ui.md) — `web/` (FastAPI, router, Jinja2/htmx templates)
- [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md) — implicit TODOs, known limits,
  history of the price migration and the TUI-to-web migration
- [07-grading.md](07-grading.md) — architecture of the Grading module: formula, thresholds, weights,
  how to tune them
- [08-cardtrader-pricing.md](08-cardtrader-pricing.md) — architecture of CardTrader pricing:
  matching, rate limiting, known limits
