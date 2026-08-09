# Notes, known limitations, and things to watch out for

## History: from YGOPRODeck to CardTrader for pricing

The app originally sourced prices from YGOPRODeck (`card_sets[].set_price` /
`card_prices[].cardmarket_price`). The user reported prices far higher than reality (e.g.
€1.20 shown vs €0.20 seen on CardTrader) — investigating, the YGOPRODeck documentation doesn't
specify the origin/update frequency of `set_price`, and `cardmarket_price` is documented as "the
lowest price across all versions of the card" (not specific to the selected printing):
neither was a reliable market price.

First attempt: a Cardmarket API via RapidAPI (`cardmarket-api-tcg`, provider tcggo). Dropped
after direct empirical verification (real authenticated calls): **it has no data for Yu-Gi-Oh!**
(nor for Magic/One Piece), only Pokémon and Lorcana. All references to RapidAPI were removed
from the project (config, `.env`, local permissions, any MCP server).

Adopted **CardTrader** (a real marketplace, not an aggregator) as the sole price source.
YGOPRODeck stays in the project but **only for card search/identification** — none of its
price fields are shown or used in any calculation anymore. Full details in
[08-cardtrader-pricing.md](08-cardtrader-pricing.md).

## History: from JSON to SQLite for the collection

Motivation: `collection.json` was rewritten in full (`json.dump`) on every save, with no
atomicity or locking — a crash mid-write could corrupt the file. As long as the collection was
purely for viewing, the risk was low; with the selling feature coming (see next section)
the data becomes financially relevant too, and a **stable row id** is also needed
to be able to hook future relational tables (`listings`/`orders`) to a specific
card stack — something a JSON list without ids doesn't allow.

Decisions made (discussed and explicitly confirmed by the user before implementation):
- `pending_gradings.json` **stays unchanged** (a separate JSON file, embeds base64 photos, no
  link to selling — see [07-grading.md](07-grading.md)).
- Migration of existing data via a **one-off manual script**
  (`scripts/migrate_to_sqlite.py`), not automatic on app startup — a deliberate choice to
  have an explicit, controllable checkpoint instead of a silent conversion.
- Only `collection.json` → SQLite is in scope; `collection.csv` remains a derived artifact,
  regenerated every time, not moved into the DB.

**Technical risk identified and resolved**: a naive implementation of `save_collection()` with
a full `DELETE` + re-`INSERT` of everything would have defeated the very purpose of the migration,
reassigning new `AUTOINCREMENT` values on every save (the method is called after almost every
mutation). Solved with upsert-by-known-`row_id`-then-prune — full implementation detail in
[04-services.md](04-services.md).

**Deliberately NOT added**: a `UNIQUE` constraint on `(id, set_code, rarity, grade)` in the
SQL schema. SQLite treats NULL values as distinct in a UNIQUE index, so it would not correctly
enforce "all ungraded stacks merge with each other" for `grade IS NULL`.
The merge/identity logic stays entirely in `AppState.add_card_to_collection` (Python,
`web/state.py`), exactly as with JSON's zero constraints — a DB constraint here would be
new, never-tested behavior, not a restoration of prior behavior.

See [03-data-models.md](03-data-models.md) (new `row_id` field on `CollectionItem`) and
[04-services.md](04-services.md) (schema, write strategy, migration script) for
details. The full implementation plan is also saved in
`C:\Users\ferla\.claude\plans\cosmic-giggling-rain.md` (outside the repo, a Claude Code plan file).

## Selling cards on CardTrader (bulk + single)

Implemented in the session following the SQLite migration above (same motivation: the
stable `row_id` exists specifically for this). Bulk selling and single-card selling share
**the same staging/review flow** — a pattern borrowed from `pending_gradings`
(a flat list indexed by id, each row independently actionable), not from Bulk Add's
one-at-a-time cursor: "sell a card" is simply "stage a single row".

**Design decided with the user and honored in the implementation**:
1. **Blueprint resolved and persisted once** — `CollectionItem.cardtrader_blueprint_id`/
   `cardtrader_blueprint_image_url` (new columns, additive migration in
   `services/storage.py`). Never recomputed after the first match: unlike the price
   (`find_real_prices`, where a wrong match is just a skewed number), here a wrong match
   would decide which physical card is being promised for shipment. If ambiguous, the user
   disambiguates once by choosing among the candidates (with their images), and the choice
   stays fixed.
2. **Condition never assumed**: the staging form (`_sell_staging.html`) starts empty/required
   for ungraded cards; pre-filled only if the card already has a grade.
3. **Visual anti-mismatch check**: every row in staging shows the `image_url` of the resolved
   CardTrader blueprint (or of the candidates, if ambiguous) before it can be confirmed.
4. **Local idempotency**: `StorageService.get_active_listing_for_row()` blocks both double
   staging and double creation if an `active` listing already exists for that stack.
5. **No webhook**: `POST /sell/poll-orders` is the only (manual) way to detect sales,
   via `GET /orders`. It never touches `CollectionItem.quantity` — reconciling a sale with the
   owned quantity remains a manual operation (a known limitation, not a bug).
6. **Language always chosen manually per row, never inferred from `set_code`**: the user
   reported that their physical collection is entirely in Italian, but during search/
   add (`services/ygoprodeck_api.py`) the YGOPRODeck API only returns English printings —
   so `CollectionItem.set_code` (e.g. `RA01-EN001`) **does not reflect the actual language of
   the physical copy owned**. Persisting/inferring a language from that for selling would have
   been wrong almost always for this collection. Solution: `SellStagingItem.language` is a
   select field editable per row in `_sell_staging.html` (`config.CARDTRADER_SELL_LANGUAGES`,
   options IT/EN/FR/DE/ES), pre-selected to `config.DEFAULT_SELL_LANGUAGE = "it"` but always
   overridable — not an indisputable silent default. Passed to
   `create_listing(..., language=...)` and persisted on `Listing.language` (new column,
   additive migration like the others). Lower risk than blueprint/condition: a wrong
   language doesn't misrepresent which physical card is being sold, only the declared
   language — for this reason, if the submitted value isn't among the valid ones, it silently
   falls back to the default instead of blocking the row (unlike condition, which always
   blocks if missing).
7. **Automatic suggested price**: when a condition is selected/pre-selected, the price
   field auto-fills with `get_price_for_condition(condition) * (1 - config.SELL_SUGGESTED_PRICE_DISCOUNT)`
   (10% discount by default, tunable in `config.py`) — it remains freely editable regardless,
   it's just a starting point. For cards already graded, the price is pre-filled server-side at
   staging time (`web/routers/sell.py::sell_stage`); for a manually chosen condition, the
   update happens client-side in `web/static/sell.js` (event delegation on
   `document.body`, not on individual `<select>` elements, because `#sell-page-content` is
   entirely re-rendered by htmx after every action — a listener on a single element would need
   to be re-attached on every swap, delegation avoids that). The suggested prices for all 5
   conditions are embedded per row as `data-prices` (JSON) on the condition `<select>`,
   computed in `_sell_context()` — no network call on condition change.

**Schema**: new `listings` table (`services/storage.py`) — `collection_row_id` (FK to
`collection_items.row_id`, **not enforced at the DB level** because the app never enables
`PRAGMA foreign_keys`; integrity is handled procedurally: `/collection/delete`
(`web/routers/collection.py`) blocks deletion of a stack that has an `active` listing).

**Real bugs discovered during live testing (POST /products), not derivable from
documentation alone**:
- The created product's id is nested in `response["resource"]["id"]`, not in a top-level
  `id` field — the real response is `{"result": "success"|"warning", "warnings": {...},
  "resource": {...}}`. `CardTraderAPI.create_listing()` already returns `resource` "unwrapped"
  precisely so callers don't have to deal with this envelope.
- The property for language is **not** called `language` but `yugioh_language` — sending
  `language` doesn't cause an error, it's silently ignored with a warning in the response
  (`"Not allowed property language has been ignored"`), which is more insidious than a 422
  because the rest of the request still succeeds. `condition`, on the other hand, is the
  correct key, as had been assumed.
- The initial probe (empty/incomplete payload on `POST /products`) correctly confirmed the
  top-level schema (`blueprint_id`/`price`/`quantity` as flat fields, `price` a plain number
  not nested in `{cents, currency}`) — that part required no corrections.

**Verified live end-to-end** (with explicit user confirmation for the real listing,
which was then deleted immediately after): creation of a real listing for a low-value card
(Neo-Spacian Glow Moss, STON-EN006), verification via `GET /products/export`, deletion via
`DELETE /products/:id`, verification that it was gone — a full round trip confirmed working
with the fix above. The token's Full API/seller access had already been confirmed earlier
(`GET /products/export`, `GET /orders`, `GET /info` → 200 before this feature).

**Explicit known limitations** (not implemented in this v1, by choice):
- No automatic reconciliation between a sold listing and the quantity owned in the collection.
- Idempotency is local only: if a listing is deleted manually from the CardTrader website, the
  local record stays "active" until it's also deleted here (harmless: it only blocks a
  re-listing, no risk of a real duplicate). The opposite risk — the local DB losing track of an
  active listing while it's still live on CardTrader — is not mitigated; it would require
  cross-checking `GET /products/export` against the local data in `/sell/poll-orders`.
- `GET /orders` has not yet been observed with a real order — `sell_poll_orders`
  (`web/routers/sell.py`) defensively extracts sold product ids from a couple of plausible
  key paths; it should be revisited on the first real sale.
- No cap on the quantity being sold relative to the quantity owned (just a default, freely
  editable).

Main files: `services/cardtrader_api.py` (`resolve_blueprint_for_sale`, `create_listing`,
`delete_listing`, `list_orders`), `services/storage.py` (`listings` table + CRUD),
`web/routers/sell.py` (all `/sell/*` routes), `web/state.py` (`SellStagingItem`,
in-memory, never persisted — unlike `pending_gradings`, it's cheap to reconstruct).

## Real bug: inflated prices due to a wrong language filter in `find_real_prices`

Discovered by the user while manually checking a price (D.D. Assailant, SDDE-EN017): the app
showed NM=€3.51/LP=€4.30 while CardTrader had real Italian listings from €0.19. Cause: `lang` in
`CardTraderAPI.find_real_prices()` was inferred from the `set_code` (e.g. "EN" from
"SDDE-EN017") and used to filter marketplace listings by language — but the stored `set_code`
is **always** English (YGOPRODeck only returns English printings in search, see "Language
always chosen manually" above), so the price calculation only looked at the handful of English
listings (few, expensive) instead of the real Italian listings (many, cheap) — exactly the
price the user actually saw on CardTrader.

**Fix**: `lang` in `find_real_prices` now directly uses `config.DEFAULT_SELL_LANGUAGE` ("it")
instead of the token parsed from `set_code` — the same conceptual fix already made on the
selling side (see above), extended to the reading/pricing side that had remained uncovered.

**Measured real-world impact**: after the fix, refreshing the entire collection (172 cards) →
**135 cards (78%) with an NM price change > 15%**, almost always downward (previously inflated
prices). Not an isolated case: the bug systematically affected almost every card.

**Consequence for already-created real listings**: the 33 active listings on CardTrader
(created by the user before this fix) had prices calculated with the wrong formula — fixed
manually one by one via the new `CardTraderAPI.update_listing_price()` method
(`PUT /products/:id`, schema confirmed live with a probe on a real listing before
bulk use) right after the fix (31 updated, 2 already correct by chance, 0 failed).
Also added a permanent route/button to redo this in the future without an ad-hoc script:
`POST /sell/listings/sync-prices` (`web/routers/sell.py`) + a "💶 Sync prices" button in
`_sell_listings.html` — realigns every active listing to the current suggested price
(`get_price_for_condition(condition) * (1 - SELL_SUGGESTED_PRICE_DISCOUNT)`), useful every
time collection prices change after a listing has already been created (price refresh,
other future bug fixes, etc.) — a listing does not automatically follow the collection's
prices, it's a snapshot taken at creation time.

## History: from Textual TUI to web app (FastAPI + htmx)

The Grading module (photo + analysis overlay) exposed a fundamental limitation of the TUI:
terminal image rendering (`textual-image`) caused **two non-trivial bugs** during the session:
1. Visual overlap between the analysis box and the "Link grade" box — real cause: the
   bordered containers (`.box_panel`) never had an explicit `height` in CSS, so
   Textual treated them as `1fr` (dividing available space equally among siblings, not
   sizing to content). With small content it went unnoticed; once the image row was added, the
   box exceeded its "quota" and its tail got written underneath the next box. Diagnosed by
   measuring widget `region`s with `run_test()` at different terminal sizes: the breaking
   point scaled exactly with half the screen height, not with the content — decisive proof
   that it was a space-distribution problem, not a sizing one. Fix applied (`height: auto` on
   `.box_panel`) and working.
2. Right after, a second bug: the displayed images weren't scaled to fit the box —
   only a cropped portion at native resolution was visible (an edge case of `textual-image`
   with dynamic image assignment after widget mount, not fixable with a quick change on our
   side).

At that point the user decided to retire the TUI and build a web front-end, accepting the
rebuild effort in exchange for reliable image rendering (browsers handle scaling natively, with
no need for any terminal graphics protocol). Migration carried out in the same session: **all
business logic (`services/`, `models.py`, `config.py`) was reused without changes** — only the
control/presentation layer was rebuilt, from `ui/app.py` + `ui/views/*.py` (Textual, removed) to
`web/` (FastAPI + Jinja2 + htmx). See [02-architecture.md](02-architecture.md) and
[05-ui.md](05-ui.md) for the current architecture.

## Architectural limitation: grading and stacked quantities (`CollectionItem`)

`CollectionItem` represents a **stack** of N identical copies (same id/set_code/rarity) with
a single base price — not individual physical cards. The Grading module, however, judges a
specific physical copy, which is conceptually in tension with the stack model.

**Solution adopted** (minimal, reversible, no extensive refactor): cards with a `grade`
set are no longer merged into other stacks with the same id/set_code/rarity but a **different
grade** — the match key in `AppState.add_card_to_collection` (`web/state.py`, ported from the
old `add_card_to_collection_logic` in `ui/app.py`) now also includes the grade. Ungraded cards
(`grade=None`, the normal case for Add Card / Bulk) continue to behave exactly as before.

**Why**: to avoid an extensive data-model refactor (per-physical-copy tracking instead of
per-stack), which would have required reworking storage, CSV export, bulk-add, and
collection_view — not justified just to occasionally grade a few valuable cards.

**How to extend it**: if in the future it's necessary to track multiple grades for the same
card/set/rarity at quantity > 1 (e.g. 3 copies graded differently), this behavior already
allows it (separate stacks get created); if instead true per-copy tracking is needed across the
whole collection, the data model needs to be reevaluated from scratch.

## Dependency on the local Ollama server

The "🩺 Card Grading" page requires the Ollama server to be running (`docker compose up -d`,
see [01-stack-and-setup.md](01-stack-and-setup.md)). If it isn't running, the analysis fails
with an `InspectorAgentError` shown in the response partial (not a crash) — the rest of the
app's pages remain fully functional. The first time the container starts, it needs to pull the
`llava` model (a few GB): this can take a few minutes the first time.

## Tunable grading formula

The CV thresholds (edge wear, centering deviation), the sub-score weights, and the
grade→condition mapping are named constants in `config.py`, meant to be tuned by observing
real-world results (they have not been validated against a dataset of physical cards). Details
and rationale in [07-grading.md](07-grading.md).

## Declared scope limitation: no "Corners" sub-score

Real PSA/BGS grading uses 4 sub-scores (Centering, Corners, Edges, Surface). This system
implements only 3: neither the geometric agent nor the VLM prompt (which explicitly ignores
edges and centering) covers detection of worn/rounded corners. This is a known limitation,
not a bug — see [07-grading.md](07-grading.md) for how to extend it in the future.

## Collection data committed to git

`collection.json` (~1700 lines) and `collection.csv` (~170 lines) are described as
"auto-generated" files but contain real data from a test/development collection and are
committed to the repository (they aren't in `.gitignore`). After the SQLite migration (see
above), these two files **are no longer written by any application flow** — they remain in git
only as a frozen snapshot from the time of the migration, while the real active store
(`collection.db`) is correctly in `.gitignore`. The "user data tracked in git" inconsistency
already existed before this step and was not resolved unilaterally (it would require an
explicit decision from the user, e.g. removing `collection.json`/`.csv` from git tracking now
that they're just backups).

Different, deliberate treatment for `pending_gradings.json` (the Grading module's inbox, see
[07-grading.md](07-grading.md)): it **is** in `.gitignore`, because it contains base64 card
photos (hundreds of KB per card) — committing it would bloat the repository with binary data in
a way that `collection.json`/`.csv` (text/numbers only) don't. This isn't an inconsistency with
the choice above, just a different case-by-case judgment call.

## Important operational constraints

- **YGOPRODeck rate limit**: `config.API_RATE_LIMIT_DELAY = 0.05` (seconds). The README
  explicitly warns not to lower this value to avoid an IP ban. It must be respected in any new
  feature that calls the API in a loop (e.g. bulk add).
- **CardTrader rate limit**: `config.CARDTRADER_RATE_LIMIT_DELAY = 0.1` (seconds), below the
  actual limit of 200 requests/10s globally (10/s on `/marketplace/products`). See
  [08-cardtrader-pricing.md](08-cardtrader-pricing.md).
- **Secrets management**: the project has a `.env` file (git-ignored, with `.env.example` as a
  template) containing `CARDTRADER_TOKEN`, loaded by `config.py` via `python-dotenv`. YGOPRODeck
  remains public with no key needed; the Grading module uses a local VLM (Ollama), also with no
  key.

## What's structurally missing

- No "formal" automated tests (no `pytest`, no `tests/` folder) — verification done with
  ad-hoc scripts/`TestClient` during development, not a persistent test suite in the repo.
- No CI/CD (`.github/workflows/` absent)
- No `LICENSE`
- "Silent" error handling: `ygoprodeck_api.py`/`storage.py` use broad `try/except` blocks with
  `print()` to stdout, rather than propagated exceptions or a structured logging module. The
  Grading module (`services/grading/`) intentionally deviates from this convention: it raises
  typed exceptions (`CardCropError`, `InspectorAgentError`) with understandable messages,
  caught and shown in the response partial by `web/routers/grading.py` — this pattern should be
  preferred for new code.

## Observed code conventions (to stay consistent in future changes)

- Descriptive docstring at the top of every module
- `snake_case` for functions/variables, `PascalCase` for classes
- Systematic type hints (`typing.List`, `Optional`, `Dict`)
- Data models always via Pydantic `BaseModel` with explicit defaults
- Card condition codes standardized to 2 uppercase letters (`NM`, `EX`, `GD`, `LP`, `PO`),
  used consistently in `config.py`, `models.py`, and the templates
- UI text/notifications in Italian, code comments in English
- Every web page has a "full" template + one or more partials (prefixed `_`) reused both on
  first load and as the response for endpoints invoked by htmx — see
  [05-ui.md](05-ui.md).
