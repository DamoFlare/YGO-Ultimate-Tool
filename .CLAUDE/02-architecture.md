# Architecture

## Folder structure (files tracked by git)

```
YGO-Ultimate-Tool/
├── .gitignore
├── README.md
├── requirements.txt
├── docker-compose.yml           # self-hosted Ollama server for the Grading module
├── docker/
│   ├── Dockerfile                # based on ollama/ollama:latest
│   └── ollama-entrypoint.sh      # starts the server and pulls `llava` on first run
├── config.py                    # global constants / configuration (incl. WEB_HOST/PORT, grading thresholds)
├── models.py                    # Pydantic data models (incl. GradingResult)
├── main.py                      # entry point: starts uvicorn on web.app:app
├── collection.json              # user collection data (actual persistence)
├── collection.csv               # CSV export of the collection
├── test_col.json                # minimal sample file (1 card)
├── test_col.csv                 # corresponding CSV export
├── .env                          # CARDTRADER_TOKEN (git-ignored, copy from .env.example)
├── .env.example
├── services/
│   ├── ygoprodeck_api.py        # async HTTP client to the YGOPRODeck API (card lookup only)
│   ├── cardtrader_api.py        # client to CardTrader (sole price source, see 08-cardtrader-pricing.md)
│   ├── storage.py               # JSON/CSV persistence
│   └── grading/
│       ├── __init__.py
│       ├── geometric_agent.py   # deterministic CV: normalization, edge wear, centering, overlay
│       ├── ai_agent.py          # async Ollama client (VLM `llava`) for the surface
│       └── grader.py            # orchestrator: combines both agents into the final 1-10 grade + debug images
└── web/                         # FastAPI application (presentation layer)
    ├── __init__.py
    ├── app.py                   # creates the FastAPI app, lifespan (init/teardown of AppState), mounts the routers
    ├── state.py                 # shared AppState: API clients, in-memory collection, multi-step queues/flows
    ├── deps.py                  # FastAPI dependency injection: Jinja2 templates, access to AppState
    ├── routers/
    │   ├── __init__.py
    │   ├── collection.py        # Collection page: table, filter/sort, price refresh, delete, CSV export
    │   ├── add_card.py          # Add Card page: search, confirmation
    │   ├── bulk_add.py          # Bulk Add page: queue, confirm/skip, save all
    │   └── grading.py           # Grading page: upload, analysis, search to link, save
    ├── templates/                # Jinja2 HTML: 4 pages + partials for htmx updates
    └── static/
        ├── htmx.min.js           # vendored, not from a CDN
        └── style.css             # hand-written CSS, dark theme — no CSS framework
```

There is no `docs/`, `CONTRIBUTING.md`, `LICENSE`, `Makefile`, `.github/workflows/`, `tests/`,
`pyproject.toml`.

Historical note: the project went through two UI architectures before the current one. First a
placeholder OCR/Vision scanner module (removed), then a **full Textual TUI** (4 tabs, with all the
business logic inside `ui/app.py`) — this too was **removed entirely**, retired in favor of the
current web app because rendering images from the terminal (needed for the transparency of the
Grading module) proved unreliable (two non-trivial library bugs encountered during the session).
If you find references to `ui/`, `YGOValuerApp`, `textual`/`textual-image` elsewhere (old commits,
notes), they are outdated — see [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md)
for the full history.

## Logical layers

A 3-layer application, now more cleanly separated than in the TUI era:

1. **Config/data** (root): `config.py`, `models.py` — shared constants and Pydantic models.
2. **Services** (`services/`): external logic, persistence, and — new compared to the TUI — also
   part of the application orchestration (`AppState.add_card_to_collection` in `web/state.py` is
   an almost 1:1 port of what in the TUI was `add_card_to_collection_logic` inside
   `ui/app.py`; here it lives in `web/` because it is still tied to the app's shared state, not
   because it has gone back to being "presentation logic").
3. **Web** (`web/`): FastAPI routers (one file per page) + Jinja2/htmx templates. Each handler is
   deliberately thin: reads input, calls the services/`AppState`, renders a template.

## Entry point and shared state

```
main.py
  └── uvicorn.run("web.app:app", host=config.WEB_HOST, port=config.WEB_PORT)
```

`web/app.py` uses FastAPI's `lifespan` to create an instance of `AppState` (in
`web/state.py`) on startup and close it on shutdown:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ygo = AppState()   # api, cardtrader, storage, grader, collection loaded from disk
    yield
    await app.state.ygo.close()  # closes the httpx/Ollama sessions
```

`AppState` is **a single, process-wide, in-memory global state** — there are no per-user/
per-browser-tab sessions. This is the same mental model as the old TUI (a single process, a
single state), simply moved from attributes of a Textual `App` class to attributes of this
shared object accessed via `request.app.state.ygo` (accessible in routers through the
`web.deps.get_state` dependency). A known and accepted limitation, not a missed design flaw: see
[06-notes-and-discrepancies.md](06-notes-and-discrepancies.md).

## Main request flow

1. **Card search**: `POST /add/search` (form `query`) → `YGOProDeckAPI.search_cards(query)`
   (cascade: numeric passcode → set code → fuzzy by name) → the `_add_results.html` template
   shows each card found **with all its printings/sets already listed below it** (no second
   server-side selection round: each set row already carries `card_id`+`set_code` in hidden
   fields of its own form). **No price shown at this stage**: YGOPRODeck here is only used to
   identify the card.
2. **Adding to the collection**: `POST /add/confirm` (form `card_id`, `set_code`, `rarity`, `qty`)
   → calls `YGOProDeckAPI.get_card_by_id` again (one extra call, stateless by design) to
   retrieve the full card object → `AppState.add_card_to_collection()` calls
   `CardTraderAPI.find_real_prices(set_code, rarity)` for the real price, creates/updates a
   `CollectionItem` → the router saves to disk (`StorageService.save_collection`). If CardTrader
   finds no match, the price stays `0.0` — a YGOPRODeck price is never used as an estimate.
3. **Bulk adding**: `POST /bulk/load` (form `codes`) resolves each code via YGOPRODeck and
   populates `AppState.bulk_queue`/`bulk_index`. `POST /bulk/confirm`/`POST /bulk/skip` advance
   the queue one step at a time (staged in memory, not saved to disk). `POST /bulk/save-all`
   persists everything together at the end of the queue — the same "confirm before saving"
   semantics as the TUI.
4. **Price refresh**: `POST /collection/refresh-prices` re-queries **only CardTrader** for
   every card in the collection and updates `real_condition_prices`/`base_price`/`price_source`.
5. **Display/valuation**: `GET /` and `GET /collection/table` (the latter called via htmx for
   live filter/sort without a reload) read `AppState.collection`, call
   `item.get_price_for_condition(cond)` for each condition (real CardTrader prices with
   fallback to the `config.CONDITION_MULTIPLIERS` multipliers only where an active listing is
   missing), compute the aggregate metrics, and render `_collection_content.html`.
6. **Grading**: cropping the card is manual (the user drags 4 corners on the uploaded photo,
   `web/static/corner-picker.js`), no longer auto-detected — see [07-grading.md](07-grading.md)
   for why. `POST /grading/analyze` (multipart upload `image` + `corners`) saves the file to a
   temp path, calls `CardGrader.grade_card(path, corners)` (which returns `(GradingResult,
   DebugImages)`), then **deletes the temporary file** and embeds the two images
   (`DebugImages.original`/`.annotated`) as base64 PNGs directly in the response HTML
   (`web.state.image_to_data_uri`) — no terminal graphics protocol, no file to serve via a
   static route. The result goes into `AppState.pending_gradings` (a list, no longer a single
   slot — needed for several graded cards waiting at the same time, both from a single photo
   and from **Bulk Grading**: multiple photos/a folder, the same manual cropping applied one
   at a time, the same `/grading/analyze` call made via `fetch()` from a client-side sequencer)
   until `POST /grading/save` (with an explicit `pending_id`) links it to a card in the
   collection. Full details in [07-grading.md](07-grading.md) and [05-ui.md](05-ui.md).

## Concurrency

All calls to external APIs (YGOPRODeck, CardTrader, Ollama) are `async`/`await`
(via `httpx.AsyncClient` and `ollama.AsyncClient`), and FastAPI/uvicorn run on an asyncio
event loop — every router handler is itself `async def`. Manual rate limiting with
`asyncio.sleep` to respect the YGOPRODeck and CardTrader limits separately (see
[04-services.md](04-services.md) and [08-cardtrader-pricing.md](08-cardtrader-pricing.md)). The
grading call (potentially slow, seconds on CPU for Ollama inference) simply keeps the HTTP
request open until it responds — no server-side worker/spinner: the UI shows a client-side
loading indicator (htmx's `hx-indicator`) for the duration of the request.
