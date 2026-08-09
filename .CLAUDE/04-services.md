# Services (`services/`)

## `services/ygoprodeck_api.py` — `YGOProDeckAPI` class (card lookup only, NEVER prices)

Asynchronous HTTP client (`httpx.AsyncClient`) for the public **YGOPRODeck** API
(`https://db.ygoprodeck.com/api/v7/`). No authentication required.

⚠️ **Used exclusively to identify cards** (name, passcode, available sets/rarities).
The price fields this client parses (`CardSetInfo.set_price`, `CardPrices.*`) **are never
shown to the user nor used to compute a price**: their origin/update frequency is not
documented by YGOPRODeck, and they turned out to be very far from real market prices (see
[06-notes-and-discrepancies.md](06-notes-and-discrepancies.md)). The only price source is
`services/cardtrader_api.py` (below).

- Manual rate limiting: `_rate_limit()` with `asyncio.sleep(config.API_RATE_LIMIT_DELAY)` before
  each call, to stay under ~20 requests/second.
- `search_cards(query)` — cascading search logic:
  1. if the query is **numeric**, tries an exact passcode/ID search
  2. if it contains `-` (or `.` normalized to `-`), tries to interpret it as a **set code**
     (e.g. `RA01-EN001`): resolves the set prefix via `get_all_sets()` (`cardsets.php`
     endpoint, result cached in memory), then calls `get_cards_by_set_name`
  3. fallback: **fuzzy search by name** via the API's `fname` parameter
- `get_card_by_id(id)` — direct search by passcode
- `get_cards_by_set_name(set_name)` — search by resolved set name
- `_parse_card_json(...)` — transforms the API's raw JSON into a `CardSearchResult` (see
  [03-data-models.md](03-data-models.md))
- `close()` — closes the httpx session; called from `web/app.py`'s `lifespan`
  (`await app.state.ygo.close()`) on server shutdown to avoid dangling connections

## `services/cardtrader_api.py` — `CardTraderAPI` class (sole price source)

Asynchronous HTTP client for the authenticated **CardTrader** API
(`https://api.cardtrader.com/api/v2`, Bearer token from `.env`/`config.CARDTRADER_TOKEN`).
Full description of the architecture, matching formula, and known limitations in
[08-cardtrader-pricing.md](08-cardtrader-pricing.md); here just a summary:

- `find_real_prices(set_code, rarity)` — main function: resolves the YGOPRODeck set_code
  (e.g. `LOB-001`) into a CardTrader expansion + card, queries the real marketplace listings
  (`/marketplace/products`), and returns the minimum price for each NM/EX/GD/LP/PO condition
  that has active listings. Returns `None` (never an exception) on any failure — no
  match, no listings, network down, invalid token — so as to never break the
  add/refresh flow of the collection.
- In-memory cache for stable data (expansions, blueprints per expansion), no cache for
  marketplace listings (prices change in real time).
- Rate limiting with the same pattern as `YGOProDeckAPI._rate_limit` (`config.CARDTRADER_RATE_LIMIT_DELAY`).

**Selling methods** (added for the selling feature, see
[06-notes-and-discrepancies.md](06-notes-and-discrepancies.md) for design and real bugs discovered live):
- `_resolve_blueprint_candidates(set_code, rarity)` — matching logic extracted from
  `find_real_prices` (steps 1-3: parse → expansion → collector_number/rarity filter), shared
  by both public methods, **does not** catch exceptions (leaves that decision to the caller).
- `resolve_blueprint_for_sale(set_code, rarity)` — unlike `find_real_prices` (which tolerates
  "no match" and always returns `None` on error), explicitly distinguishes
  `resolved`/`ambiguous`/`not_found`/`error` — the selling UI must react differently to each.
- `create_listing(blueprint_id, price_eur, quantity, condition_bucket, language="en")` —
  `POST /products`. **Unlike `find_real_prices`, it propagates errors**
  (`CardTraderAPIError`) instead of swallowing them: a sale failure must be visible.
  Body confirmed live (probe + real test with immediate deletion): `blueprint_id`/
  `price`/`quantity` are flat fields, `price` is a plain number (not `{cents, currency}`). The
  property for the language is `yugioh_language`, **not** `language` (the latter is silently
  ignored with a warning, not rejected — a real bug found during the live test). The method
  returns `response["resource"]` already "unwrapped" (the real response is
  `{"result": ..., "warnings": ..., "resource": {...}}`, with the created product's id nested in
  there, not at the root level).
- `update_listing_price(product_id, price_eur)` — `PUT /products/:id`, same schema as
  `create_listing` (flat `price`), confirmed live with a probe on a real listing before
  bulk use (see [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md), inflated
  price bug). Updates the price while keeping the same product id (unlike
  delete+recreate). Used by `POST /sell/listings/sync-prices` to realign active
  listings when the collection price changes after the listing was created.
- `delete_listing(product_id)` — `DELETE /products/:id`, a 404 is treated as success
  (idempotent cancellation).
- `list_orders()` — `GET /orders`. Response shape **not yet observed with a real order**
  (only "200, empty list" verified) — the caller (`web/routers/sell.py`) must be written
  defensively and revisited on the first real sale.

## `services/storage.py` — `StorageService` class

Local persistence on **SQLite** (`collection.db`, `collection_items` table, stdlib `sqlite3`
— no new dependency). Migrated from a plain `collection.json` file; see history and rationale
in [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md). The 3 public signatures were
deliberately kept identical, so as not to have to touch any call site in `web/state.py`/`web/routers/*.py`:

- `load_collection()` — `SELECT *` on the table, ordered by `row_id` (insertion order);
  deserializes `grade_breakdown`/`real_condition_prices` from JSON text to dict. Same permissive
  contract as before: any exception (corrupted DB, lock, etc.) is logged with `print()` and
  returns `[]`, not propagated.
- `save_collection(collection)` — always receives the **entire current list** (same semantics
  as before: "the in-memory list is the source of truth, storage persists a snapshot of it"), but
  it does **not** do a blind `DELETE`+`INSERT` of everything: that would lose `row_id` stability on every
  save (the method is called after almost every mutation — add, refresh-prices, delete,
  bulk-save-all, grading-link — and an `AUTOINCREMENT` reassigned each time would shuffle the ids).
  Strategy used: **upsert by known `row_id`, then prune** — for each item with an already
  assigned `row_id` it does `UPDATE ... WHERE row_id=?` (defensive fallback to `INSERT` if the update touches
  no rows); for each new item (`row_id is None`) it does `INSERT` and repopulates `item.row_id =
  cursor.lastrowid` (the only mutation the method makes on the input, purely additive); finally
  it deletes from the table any row whose `row_id` is no longer present in the given list (this
  is the mechanism `/collection/delete` relies on, which rebuilds `state.collection` by
  filtering and then calls `save_collection` again). All in a single transaction
  (`isolation_level=None` + explicit `BEGIN`/`COMMIT`/`ROLLBACK`) — unlike the old
  direct `json.dump`, a crash mid-write no longer corrupts the data.
- `export_to_csv()` — **unchanged**: generates `collection.csv` with detailed columns for each
  condition (id, name, set_code, set_name, rarity, grade, condition, quantity, base_price_NM,
  price_EX/GD/LP/PO, total_NM_value, total_effective_value, price_source). Depends only on
  receiving a `List[CollectionItem]`, not on the storage backend.

`scripts/migrate_to_sqlite.py` — one-off script (never run automatically at startup) that
imports `collection.json` into `collection.db` the first time: unlike `load_collection()`
it fails loudly on any problem (missing file, invalid JSON, a row that doesn't validate
as `CollectionItem`, `collection.db` already populated) instead of silently degrading to an empty
list. It never touches/deletes `collection.json` (it remains as a backup).

**`listings` table** (selling feature, see [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md)):
rows created/managed by `load_listings()`, `get_active_listing_for_row()` (the idempotency
check used by `web/routers/sell.py` before staging or creating a listing),
`create_listing()` (backfills `Listing.id` from `lastrowid`, same pattern as
`save_collection()`'s `row_id`), `update_listing()`. No `FOREIGN KEY` declared toward
`collection_items.row_id` — the app never enables `PRAGMA foreign_keys`, so a constraint
that's declared but not enforced would be misleading; integrity is guaranteed procedurally by the
guard in `/collection/delete` (see [05-ui.md](05-ui.md)), not at the DB level.

## `services/grading/` — Hybrid Grading module (CV + local VLM)

Entirely replaces the old `services/scanner.py`/`CardScannerService` placeholder
(removed). A real implementation, not a placeholder. Full description of the architecture,
formula, and thresholds in [07-grading.md](07-grading.md); here just a summary to orient yourself in the
code.

- **`geometric_agent.py`** — zero AI dependencies, only `cv2`/`numpy`. Details and history
  of the precision investigation (crop, edge wear, centering) in
  [07-grading.md](07-grading.md); here just a summary:
  - `normalize_card_image(path, corners)` — **no longer detects anything automatically**: it does
    a perspective warp of the quadrilateral passed by the caller (the 4 corners chosen by hand by the user
    in `web/static/corner-picker.js`) into a canonical rectangle
    (`config.NORMALIZED_CARD_WIDTH/HEIGHT`). Four rounds of automatic detection (Canny,
    HSV saturation segmentation, shape validation, edge expansion) were
    attempted and abandoned in the same session — see history in 07-grading.md. Raises
    `CardCropError` (renamed from `CardDetectionError` — the meaning has changed) if the image
    can't be opened or if `corners` doesn't have exactly 4 points.
  - `calculate_edge_wear(img)` — % of pixels in the thin perimeter with brightness above an
    **absolute whitening threshold** (`config.CARD_GRAYSCALE_WHITENESS_THRESHOLD`), no longer
    a relative distance from a reference ring (previous version, abandoned due to a
    calibration issue — see history in 07-grading.md); returns a "wear" percentage. The
    threshold has only been verified on cards in good condition (percentages close to 0 as expected),
    not yet on a card with real wear — known limitation, see 07-grading.md.
  - `calculate_corner_whitening(img)` — same absolute threshold as `calculate_edge_wear`, applied
    to a 50×50px ROI for each of the 4 corners. Measures only whitening, not the geometric
    rounding of the corner (lost by construction due to the perspective warp) — see 07-grading.md.
  - `calculate_centering(img)` — looks for the inner printed frame (convex quadrilateral contour,
    not touching the image edges, area within a plausible range) and measures the margins relative to the
    card's physical edges, returning horizontal/vertical ratios (50/50 = perfect) plus
    a `detected` flag (if `False`, the measurement is not reliable and the caller must use a
    conservative fallback, not assume perfect centering). In practice `detected` is almost always
    `False` — known limitation not yet resolved, see 07-grading.md.
- **`ai_agent.py`** — `InspectorAgent`, asynchronous client (`ollama.AsyncClient`) for the local
  Ollama server (`config.OLLAMA_BASE_URL`, model `config.OLLAMA_VISION_MODEL = "llava"`).
  `analyze_surface(img)` sends the already normalized image with `format="json"` and
  `temperature=0.1`, using the fixed system prompt `config.INSPECTOR_SYSTEM_PROMPT` (schema:
  `has_scratches`, `scratch_severity`, `has_creases`, `crease_severity`, `details`). Raises
  `InspectorAgentError` with a comprehensible message if the server doesn't respond or the JSON isn't
  parsable — **not** a raw traceback.
- **`grader.py`** — `CardGrader.grade_card(image_path)` orchestrates the two agents and produces a
  `GradingResult` (see [03-data-models.md](03-data-models.md)): runs the geometric
  agent first (sync), then the VLM inspector (async), computes the 3 sub-scores, the final
  weighted/clamped grade, and the mapped condition.

No API key required (the model runs entirely locally via Docker, see
[01-stack-and-setup.md](01-stack-and-setup.md)). The added dependencies (`opencv-python-headless`,
`numpy`, `ollama`) are in `requirements.txt`.
