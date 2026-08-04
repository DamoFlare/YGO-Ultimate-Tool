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
            prefix, lang, collector_number = parsed

            expansions = await self._get_expansions_by_code()
            expansion_id = expansions.get(prefix)
            if expansion_id is None:
                return None

            blueprints = await self._get_blueprints_for_expansion(expansion_id)
            candidates = [
                bp for bp in blueprints
                if _number_match(
                    str(bp.get("fixed_properties", {}).get("collector_number", "")),
                    collector_number,
                )
            ]
            if not candidates:
                return None

            if len(candidates) > 1 and rarity:
                rarity_lower = rarity.lower()
                rarity_matches = [
                    bp for bp in candidates
                    if (bp_rarity := bp.get("fixed_properties", {}).get("yugioh_rarity", "").lower())
                    and (rarity_lower in bp_rarity or bp_rarity in rarity_lower)
                ]
                if rarity_matches:
                    candidates = rarity_matches

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

    async def close(self):
        """Close httpx client session."""
        await self.client.aclose()
