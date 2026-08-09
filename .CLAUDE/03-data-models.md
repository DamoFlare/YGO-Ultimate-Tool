# Configuration and data models

## `config.py`

Global application constants:

- `YGOPRODECK_BASE_URL` — `https://db.ygoprodeck.com/api/v7/cardinfo.php`
- `API_RATE_LIMIT_DELAY = 0.05` (seconds) — delay between YGOPRODeck calls to stay under ~20
  req/sec. **The README explicitly warns not to lower this value, to avoid an IP ban.**
- `CARDTRADER_TOKEN`, `CARDTRADER_BASE_URL`, `CARDTRADER_YUGIOH_GAME_ID` (=4),
  `CARDTRADER_RATE_LIMIT_DELAY`, `CARDTRADER_CONDITION_MAP` — configuration for the app's single
  price source. See [08-cardtrader-pricing.md](08-cardtrader-pricing.md) for details.
- `CONDITION_MULTIPLIERS` — price multiplier per card condition relative to the NM price,
  used **only as a fallback** when CardTrader has no real listing for that specific
  condition (no longer the primary price source):
  - `NM` (Near Mint): 1.00
  - `EX` (Excellent): 0.88
  - `GD` (Good): 0.725
  - `LP` (Light Played): 0.55
  - `PO` (Poor): 0.35
- `CONDITION_NAMES` — mapping from condition code to readable name
- Default paths for persistence: `collection.json`, `collection.csv`
- Grading module constants (Ollama, CV thresholds, weights, grade→condition mapping): see
  [07-grading.md](07-grading.md), which documents them in detail.

## `models.py` (Pydantic v2 `BaseModel`)

- **`CardSetInfo`** — `set_name`, `set_code`, `set_rarity`, `set_rarity_code`, `set_price` (field
  parsed from the YGOPRODeck API but **never used anymore to compute a price shown to the user** —
  it remains only as raw data from the search result)
- **`CardPrices`** — `cardmarket_price`, `tcgplayer_price`, `ebay_price`, `amazon_price`,
  `coolstuffinc_price` (same story: parsed but no longer used for actual pricing, see
  [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md) for the history)
- **`CollectionItem`** — item persisted in the user's collection:
  - `row_id` (`Optional[int]`, default `None`) — surrogate SQLite primary key
    (`services/storage.py`), assigned on first save and then stable over time (upsert, never
    recreated from scratch). It is not part of the business identity (see below); it is meant to be
    the future FK target of a `listings` table (CardTrader sale, not yet implemented — see
    [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md)).
  - fields: `id`/passcode, `name`, `set_code`, `set_name`, `rarity`, `base_price`, `quantity`,
    `added_at`
  - optional Grading module fields (default `None`, backward-compatible): `grade` (float 1-10),
    `condition` (NM/EX/GD/LP/PO bucket mapped from the grade), `grade_breakdown` (dict with the
    sub-scores centering/edges/surface)
  - optional CardTrader pricing fields (default `None`, backward-compatible):
    `real_condition_prices` (dict `{"NM": 15.89, "EX": 12.4, ...}`, only buckets with real
    listings found) and `price_source` (`"cardtrader"` if a match was found, otherwise `None` —
    never `"ygoprodeck"`, that source has been removed from pricing)
  - optional sale-feature fields (default `None`): `cardtrader_blueprint_id`/
    `cardtrader_blueprint_image_url` — unlike `real_condition_prices`/`price_source`
    (freely recalculated on every refresh, a wrong match is just a skewed price), these
    are resolved **once** and never recalculated again: a wrong match here would decide
    which physical card gets promised for shipping to a buyer. See
    [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md).
  - `get_price_for_condition(condition)` method — **returns the real price from
    `real_condition_prices` if present for that condition; otherwise estimates it from `base_price *
    CONDITION_MULTIPLIERS[condition]`** (fallback, no longer the primary path)
  - `condition_prices` property — dictionary of all prices per condition (real where
    available, estimated elsewhere)
  - `total_nm_price` property — `base_price * quantity`
  - `effective_price` property — price at the actually graded condition (`condition`), or the
    NM price if the card is not graded (unchanged behavior for ungraded cards)
  - `total_effective_price` property — `effective_price * quantity`
- **`CardSearchResult`** — search result from the API:
  - `id`, `name`, `type`, `desc`, `race`, `attribute`
  - `card_sets: List[CardSetInfo]`
  - `card_prices: List[CardPrices]`
- **`GradingResult`** — output of the Grading module (`services/grading/grader.py`): raw
  measurements (`centering_ratio`, `edge_wear_pct`, `surface_details` from the VLM), the 3
  sub-scores (`centering_subgrade`, `edges_subgrade`, `surface_subgrade`), and the final
  result (`final_grade`, `condition`). See [07-grading.md](07-grading.md) for the full formula.
- **`Listing`** — a CardTrader sale listing (persisted in the `listings` table, see
  [04-services.md](04-services.md)): `id` (SQLite PK), `collection_row_id` (reference to
  `CollectionItem.row_id`, not enforced at the DB level), `cardtrader_blueprint_id`,
  `cardtrader_product_id` (id assigned by CardTrader on creation), `condition`, `language`
  (chosen manually per row when selling, never inferred from `set_code` — see
  [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md)), `price_eur`, `quantity`, `status`
  (`active`/`sold`/`cancelled`, `config.LISTING_STATUS_*`), `created_at`/`updated_at`/`sold_at`
  (ISO timestamps), `error_message`. Creating/deleting a `Listing` never touches
  `CollectionItem.quantity` — reconciliation remains manual.

## Persistence formats

- **`collection.db`** (SQLite) — **current source of truth** for the collection, table
  `collection_items` (see [04-services.md](04-services.md) for schema and write strategy).
  In `.gitignore` (never committed). Introduced to replace `collection.json` — see history in
  [06-notes-and-discrepancies.md](06-notes-and-discrepancies.md).
- **`collection.json`** — **legacy**: no longer read/written by the running app. It remains on
  disk only as a backup produced by the one-time migration (`scripts/migrate_to_sqlite.py`) and
  stays committed in git with the last known state before the migration (real
  test/development data, ~1700 lines) — it is a frozen snapshot, no longer to be considered up to date.
- **`collection.csv`** — human-readable export generated by `StorageService.export_to_csv()`, columns:
  `id, name, set_code, set_name, rarity, grade, condition, quantity, base_price_NM, price_EX,
  price_GD, price_LP, price_PO, total_NM_value, total_effective_value, price_source`. Logic
  unchanged since the migration (it only depends on receiving a `List[CollectionItem]`, not on how it
  was produced).
- **`test_col.json` / `test_col.csv`** — minimal sample files (a single card: Dark Magician,
  set `RA01-EN001`, Ultra Rare rarity, base price €2.5, quantity 2), likely used for
  quick manual tests during development. Not connected to the SQLite migration.

⚠️ Note: `collection.json`/`collection.csv` are still **committed to git** (not in
`.gitignore`), while the actual active store (`collection.db`) is — a pre-existing inconsistency
from before the migration (it was already the case when `collection.json` was the only source), not
unilaterally resolved in this step. To be reassessed if a repository cleanup is decided; today
`collection.json`/`.csv` in git are just a historical snapshot, no longer generated/updated by
any application flow.
