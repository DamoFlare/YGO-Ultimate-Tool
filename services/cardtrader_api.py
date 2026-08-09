"""
CardTrader marketplace API client for Yu-Gi-Oh! card prices.

Used as the primary price source (see ui/app.py add_card_to_collection_logic / refresh_all_prices),
replacing YGOPRODeck's set_price/cardmarket_price fields whose exact origin and freshness are
undocumented. CardTrader returns real, live marketplace listings (price + condition + language
per seller), which is far closer to what a user actually sees browsing the site.

Matching is heuristic: YGOPRODeck set codes (e.g. "RA01-EN001", "LOB-001") are parsed into a
set prefix + language + collector number, matched against CardTrader's expansion "code" and
blueprint "collector_number". Any failure at any step (network, no match, rate limit, bad
token) is caught and returns None so the caller can silently fall back to the existing
YGOPRODeck-derived pricing — this integration must never break the add/refresh flow.
"""
import asyncio
import re
import time
from typing import Dict, List, Optional

import httpx

import config

_SET_CODE_RE = re.compile(r"^([A-Za-z0-9]+)-([A-Za-z]{2})?(\w+)$")


def _parse_set_code(set_code: str) -> Optional[tuple]:
    """Split 'RA01-EN001' -> ('RA01', 'en', '001'), or 'LOB-001' -> ('LOB', 'en', '001')."""
    match = _SET_CODE_RE.match((set_code or "").strip())
    if not match:
        return None
    prefix, lang, number = match.groups()
    return prefix.upper(), (lang or "en").lower(), number


def _number_match(a: str, b: str) -> bool:
    return a == b or a.lstrip("0") == b.lstrip("0")


class CardTraderAPIError(Exception):
    """
    Raised by write operations (create_listing/delete_listing/list_orders) on any non-2xx
    response. Unlike find_real_prices() (which swallows every failure to never break the
    add/refresh pricing flow), a failed sell-side call must surface to the user, not silently
    do nothing — creating/cancelling a real marketplace listing is not a "best effort" operation.
    """
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"CardTrader API error {status_code}: {body}")


class CardTraderAPI:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=10.0,
            headers={"Authorization": f"Bearer {config.CARDTRADER_TOKEN}"},
        )
        self.last_request_time = 0.0
        self._expansions_by_code: Optional[Dict[str, int]] = None
        self._blueprints_cache: Dict[int, List[dict]] = {}

    async def _rate_limit(self):
        """Ensure rate limit (conservative vs. CardTrader's 200 req/10s global limit)."""
        elapsed = time.time() - self.last_request_time
        if elapsed < config.CARDTRADER_RATE_LIMIT_DELAY:
            await asyncio.sleep(config.CARDTRADER_RATE_LIMIT_DELAY - elapsed)
        self.last_request_time = time.time()

    async def _get_expansions_by_code(self) -> Dict[str, int]:
        """Bulk-fetch all Yu-Gi-Oh expansions once, cached in memory as {CODE: expansion_id}."""
        if self._expansions_by_code is not None:
            return self._expansions_by_code

        await self._rate_limit()
        try:
            resp = await self.client.get(f"{config.CARDTRADER_BASE_URL}/expansions")
            if resp.status_code == 200:
                data = resp.json()
                self._expansions_by_code = {
                    e["code"].upper(): e["id"]
                    for e in data
                    if e.get("game_id") == config.CARDTRADER_YUGIOH_GAME_ID and e.get("code")
                }
                return self._expansions_by_code
        except Exception as e:
            print(f"Error fetching CardTrader expansions: {e}")
        return {}

    async def _get_blueprints_for_expansion(self, expansion_id: int) -> List[dict]:
        """Fetch the card list for one expansion, cached per expansion_id for the session."""
        if expansion_id in self._blueprints_cache:
            return self._blueprints_cache[expansion_id]

        await self._rate_limit()
        try:
            resp = await self.client.get(
                f"{config.CARDTRADER_BASE_URL}/blueprints/export",
                params={"expansion_id": expansion_id},
            )
            if resp.status_code == 200:
                data = resp.json()
                self._blueprints_cache[expansion_id] = data
                return data
        except Exception as e:
            print(f"Error fetching CardTrader blueprints for expansion {expansion_id}: {e}")
        return []

    async def _resolve_blueprint_candidates(self, set_code: str, rarity: str) -> List[dict]:
        """
        Shared matching logic (parse set_code -> resolve expansion -> filter by
        collector_number -> narrow by rarity if still ambiguous) used by both find_real_prices
        (pricing, tolerates a wrong/no match) and resolve_blueprint_for_sale (selling, must
        distinguish "no match" from "network/auth error" and surface ambiguity to the user).
        Returns [] if nothing matches, [one] if unambiguous, [multiple] if still ambiguous after
        rarity narrowing. Does NOT catch exceptions — callers decide how to handle failures.
        """
        parsed = _parse_set_code(set_code)
        if not parsed:
            return []
        prefix, lang, collector_number = parsed

        expansions = await self._get_expansions_by_code()
        expansion_id = expansions.get(prefix)
        if expansion_id is None:
            return []

        blueprints = await self._get_blueprints_for_expansion(expansion_id)
        candidates = [
            bp for bp in blueprints
            if _number_match(
                str(bp.get("fixed_properties", {}).get("collector_number", "")),
                collector_number,
            )
        ]
        if not candidates:
            return []

        if len(candidates) > 1 and rarity:
            rarity_lower = rarity.lower()
            rarity_matches = [
                bp for bp in candidates
                if (bp_rarity := bp.get("fixed_properties", {}).get("yugioh_rarity", "").lower())
                and (rarity_lower in bp_rarity or bp_rarity in rarity_lower)
            ]
            if rarity_matches:
                candidates = rarity_matches

        return candidates

    async def find_real_prices(self, set_code: str, rarity: str) -> Optional[Dict[str, float]]:
        """
        Resolve a YGOPRODeck set_code + rarity to a CardTrader blueprint and return the lowest
        real marketplace price per NM/EX/GD/LP/PO bucket (only buckets with active listings are
        included). Returns None if no match/listings are found, or on any error.
        """
        try:
            parsed = _parse_set_code(set_code)
            if not parsed:
                return None
            # NOT the language parsed from set_code (e.g. "EN" in "SDDE-EN017") — YGOPRODeck's
            # search only ever returns English set data during Add Card (see
            # .claude/06-notes-and-discrepancies.md), so that token reflects the ONLY sets YGOPRODeck
            # exposed, never the physical card's actual printed language. Filtering by it here
            # silently priced from a tiny, unrepresentative pool of English listings instead of
            # this collection's real (Italian) market — a real bug found by the user cross-
            # checking a price by hand (D.D. Assailant: app showed prices derived only from ~4
            # English listings at €3.51-6.51, while ~30 real Italian listings started at €0.19).
            lang = config.DEFAULT_SELL_LANGUAGE

            candidates = await self._resolve_blueprint_candidates(set_code, rarity)
            if not candidates:
                return None

            blueprint_id = candidates[0]["id"]

            await self._rate_limit()
            resp = await self.client.get(
                f"{config.CARDTRADER_BASE_URL}/marketplace/products",
                params={"blueprint_id": blueprint_id},
            )
            if resp.status_code != 200:
                return None

            listings = resp.json().get(str(blueprint_id), [])
            if not listings:
                return None

            lang_listings = [
                l for l in listings
                if l.get("properties_hash", {}).get("yugioh_language", "en").lower() == lang
            ]
            if not lang_listings:
                # No listings in the requested language — a real price in another language
                # beats no price at all, so fall back to the full listing set.
                lang_listings = listings

            result = {}
            for bucket, ct_conditions in config.CARDTRADER_CONDITION_MAP.items():
                matching_prices = [
                    l["price"]["cents"] / 100.0
                    for l in lang_listings
                    if l.get("properties_hash", {}).get("condition") in ct_conditions
                ]
                if matching_prices:
                    result[bucket] = round(min(matching_prices), 2)

            return result or None
        except Exception as e:
            print(f"Error resolving CardTrader price for {set_code}: {e}")
            return None

    async def resolve_blueprint_for_sale(self, set_code: str, rarity: str) -> dict:
        """
        Resolve a YGOPRODeck set_code + rarity to a CardTrader blueprint FOR SELLING PURPOSES.
        Unlike find_real_prices (which just needs *a* price and tolerates a wrong/no match),
        selling needs to know exactly which situation occurred, since the caller must persist
        the choice once and never re-guess it — see CollectionItem.cardtrader_blueprint_id.

        Returns one of:
          {"status": "resolved",  "blueprint": {id, name, image_url, rarity, collector_number}}
          {"status": "ambiguous", "candidates": [same shape, one per candidate]}
          {"status": "not_found"}
          {"status": "error", "message": str}
        """
        try:
            candidates = await self._resolve_blueprint_candidates(set_code, rarity)
        except Exception as e:
            return {"status": "error", "message": str(e)}

        if not candidates:
            return {"status": "not_found"}

        def _shape(bp: dict) -> dict:
            fixed = bp.get("fixed_properties", {})
            return {
                "id": bp["id"],
                "name": bp.get("name", ""),
                "image_url": bp.get("image_url"),
                "rarity": fixed.get("yugioh_rarity", ""),
                "collector_number": fixed.get("collector_number", ""),
            }

        if len(candidates) == 1:
            return {"status": "resolved", "blueprint": _shape(candidates[0])}
        return {"status": "ambiguous", "candidates": [_shape(bp) for bp in candidates]}

    async def create_listing(
        self, blueprint_id: int, price_eur: float, quantity: int, condition_bucket: str,
        language: str = "en",
    ) -> dict:
        """
        Create a real marketplace listing (POST /products). Raises CardTraderAPIError on any
        non-2xx response — callers must NOT treat a failure here as "no listing, move on" the
        way find_real_prices does. condition_bucket must be one of config.CARDTRADER_SELL_CONDITION's
        keys (NM/EX/GD/LP/PO) — raises ValueError otherwise rather than silently substituting a
        wrong condition.

        NOTE: confirmed live (real create-then-delete test, one card, immediately deleted after
        verifying — see .claude/06-notes-and-discrepancies.md):
        - Top-level shape is blueprint_id/price/quantity as flat fields; price is a plain number
          in the marketplace's main currency unit (e.g. 0.20 for twenty cents), NOT a nested
          {cents, currency} object — CardTrader's own validation-error responses ("Price is not a
          number", "Quantity must be greater than 0") never hinted at a nested shape either.
        - properties.condition is correct as-is (accepted, applied exactly as sent).
        - properties.language is WRONG — CardTrader silently ignores it with a response warning
          ("Not allowed property language has been ignored") rather than rejecting the request.
          The correct key, visible in that same response's echoed properties, is
          "yugioh_language" (defaults to "en" if omitted).
        - The created product's id is nested under response["resource"]["id"], not a top-level
          "id" — the full response envelope is {"result": "success"|"warning", "warnings": {...},
          "resource": {...}}. This method returns resource (unwrapped) so callers never need to
          know about that envelope.
        """
        if condition_bucket not in config.CARDTRADER_SELL_CONDITION:
            raise ValueError(f"Unknown condition bucket: {condition_bucket!r}")

        payload = {
            "blueprint_id": blueprint_id,
            "price": round(price_eur, 2),
            "quantity": quantity,
            "properties": {
                "condition": config.CARDTRADER_SELL_CONDITION[condition_bucket],
                "yugioh_language": language,
            },
        }

        await self._rate_limit()
        resp = await self.client.post(f"{config.CARDTRADER_BASE_URL}/products", json=payload)
        if resp.status_code not in (200, 201):
            raise CardTraderAPIError(resp.status_code, resp.text)
        body = resp.json()
        return body.get("resource", body)

    async def update_listing_price(self, product_id: int, price_eur: float) -> dict:
        """
        Update an existing listing's price in place (PUT /products/:id) — keeps the same
        CardTrader product id/listing history, unlike cancel+recreate. Confirmed live (safe
        probe against a real owned product with an intentionally invalid price): same flat
        `price` field as create_listing, same validation-error style ("Price is not a number").
        Raises CardTraderAPIError on any non-2xx response.
        """
        await self._rate_limit()
        resp = await self.client.put(
            f"{config.CARDTRADER_BASE_URL}/products/{product_id}", json={"price": round(price_eur, 2)}
        )
        if resp.status_code not in (200, 201):
            raise CardTraderAPIError(resp.status_code, resp.text)
        body = resp.json()
        return body.get("resource", body)

    async def delete_listing(self, product_id: int) -> bool:
        """DELETE /products/:id. A 404 is treated as success (already gone = idempotent cancel).
        Raises CardTraderAPIError on any other non-2xx response."""
        await self._rate_limit()
        resp = await self.client.delete(f"{config.CARDTRADER_BASE_URL}/products/{product_id}")
        if resp.status_code == 404:
            return True
        if resp.status_code not in (200, 204):
            raise CardTraderAPIError(resp.status_code, resp.text)
        return True

    async def list_orders(self) -> List[dict]:
        """
        GET /orders — this seller's orders. Raises CardTraderAPIError on failure. Response shape
        beyond "200 with an empty list" is unconfirmed (no real orders exist yet) — the caller
        (web/routers/sell.py's poll-orders route) is written defensively and must be revisited
        once the first real order appears.
        """
        await self._rate_limit()
        resp = await self.client.get(f"{config.CARDTRADER_BASE_URL}/orders")
        if resp.status_code != 200:
            raise CardTraderAPIError(resp.status_code, resp.text)
        return resp.json()

    async def close(self):
        """Close httpx client session."""
        await self.client.aclose()
