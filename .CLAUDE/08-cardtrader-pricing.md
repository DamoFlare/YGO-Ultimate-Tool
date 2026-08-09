# Pricing via CardTrader (the app's only price source)

`services/cardtrader_api.py` — completely replaces the pricing based on YGOPRODeck
(`card_sets[].set_price` / `card_prices[].cardmarket_price`), which was the original cause of
the problem that motivated this work: the user noticed prices shown by the app that were much
higher than the real ones seen on Cardtrader/CardTrader (e.g. 1.20€ in the app vs 0.20€ real).
YGOPRODeck does not document the exact source/update schedule of those fields — see
[06-notes-and-discrepancies.md](06-notes-and-discrepancies.md) for the full history (including
the discarded attempt with a Cardmarket API via RapidAPI, which had no Yu-Gi-Oh! data).

## Why CardTrader

A real marketplace API (not an aggregator/historical average): every price returned is
an active sale listing from a real seller, with specific condition, language and quantity.
Requires a Bearer token (`.env` → `CARDTRADER_TOKEN`, see
[01-stack-and-setup.md](01-stack-and-setup.md)).

## Division of responsibilities: YGOPRODeck vs CardTrader

- **YGOPRODeck** (`services/ygoprodeck_api.py`): **card search/identification only** (name,
  passcode, list of available sets/rarities). None of the price fields it returns are shown to
  the user or used in any calculation anymore.
- **CardTrader** (`services/cardtrader_api.py`): **the only price source**. If no match is
  found, the price stays unknown (`0.0`) — there is no fallback to YGOPRODeck.

Reason for the split: CardTrader **does not expose a card search endpoint by name/passcode
across all expansions** (only `/blueprints/export?expansion_id=` for a single expansion at a
time — verified live, `/blueprints/search` does not exist). Building an equivalent search
engine would require downloading and locally indexing all the blueprints from the ~683 Yu-Gi-Oh
expansions (hundreds of one-off calls) — discarded for now, considered a possible future
evolution if the dependency on YGOPRODeck is to be eliminated entirely.

## Resolution chain (`CardTraderAPI.find_real_prices(set_code, rarity)`)

1. **`_parse_set_code(set_code)`** — regex `^([A-Za-z0-9]+)-([A-Za-z]{2})?(\w+)$` splits e.g.
   `RA01-EN001` into `("RA01", "en", "001")`, or `LOB-001` (without a language) into
   `("LOB", "en", "001")`.
2. **Expansion**: `_get_expansions_by_code()` makes **a single bulk call** `GET /expansions`
   (the API does not filter server-side by game), filters it client-side on
   `game_id == config.CARDTRADER_YUGIOH_GAME_ID` (**4**, confirmed via `GET /games`), and caches
   in memory as `{CODE: expansion_id}` for the whole session. Verified that CardTrader's `code`
   field matches (case-insensitively) the YGOPRODeck set prefix across several real sets: `LOB`,
   `RA01`, `SDMM`, `MRD`, `LOD`, `MFC`.
3. **Blueprint (specific card)**: `_get_blueprints_for_expansion(expansion_id)` calls
   `GET /blueprints/export?expansion_id=`, cached in memory per expansion_id. It filters by
   `fixed_properties.collector_number` (exact match, or with normalized leading zeros), then
   uses `rarity` (case-insensitive substring match, in both directions) as a discriminator when
   there are multiple candidates with the same number.
4. **Real prices**: `GET /marketplace/products?blueprint_id=` returns the active listings
   (`price.cents`, `properties_hash.condition`, `properties_hash.yugioh_language`). Results are
   filtered by language (inferred from the set code); if no listing exists in that language, the
   entire set of listings is used rather than returning nothing.
5. **Grouping by condition**: `config.CARDTRADER_CONDITION_MAP` maps the app's 5 buckets onto
   CardTrader's 6 conditions (`Mint`/`Near Mint` → **NM**, `Slightly Played` → **EX**,
   `Moderately Played` → **GD**, `Played` → **LP**, `Poor` → **PO**); for each bucket with at
   least one listing, the **minimum price** is taken. The returned dict only contains buckets
   with real listings found (never invented values).

Any exception at any point in the chain (network, invalid token, no match, no listings) is
caught and the function returns `None` — **never propagated**, so as to never break the
collection add/refresh flow in `web/state.py`/`web/routers/*.py`.

## How prices reach `CollectionItem`

- `AppState.add_card_to_collection` (`web/state.py`, called by the `add_card.py`,
  `bulk_add.py`, `grading.py` routers): `base_price` starts at `0.0`; if `find_real_prices`
  finds a match, it sets `real_condition_prices`, `price_source = "cardtrader"`, and
  `base_price = real_prices["NM"]` if present.
- `POST /collection/refresh-prices` (`web/routers/collection.py`): same logic for every
  `CollectionItem` already in the collection; final notification with the count of "real prices
  found for X/Y cards".

`models.CollectionItem.get_price_for_condition(condition)` always prefers
`real_condition_prices[condition]` if present; otherwise it estimates with
`base_price * CONDITION_MULTIPLIERS[condition]` — this fallback only makes sense when a real NM
price does exist but that specific condition has no active listings at that moment (not when the
card has no CardTrader match at all, in which case `base_price` is `0.0` and the estimate is
`0.0` for every condition).

## Rate limiting

`config.CARDTRADER_RATE_LIMIT_DELAY = 0.1` seconds between calls, the same elapsed-time-based
pattern as `YGOProDeckAPI._rate_limit`. Real limits declared by CardTrader: 200 requests/10s
globally, 10 requests/s specifically on `/marketplace/products` (the endpoint this service calls
the most).

## Known limitations

- **Heuristic matching**: works well on the standard sets tested, but can silently fail on
  promos/special editions with atypical set codes (automatic fallback to no price, never a
  crash).
- **No caching of marketplace listings**: every lookup makes a live call (prices change);
  `refresh_all_prices` on a large collection makes many sequential calls — for hundreds of cards
  this can take a few minutes, with no progress bar beyond the final notification.
- **No card search via CardTrader**: see the "Division of responsibilities" section above —
  YGOPRODeck remains necessary for this, by explicit choice (not a technical limitation to be
  solved).
