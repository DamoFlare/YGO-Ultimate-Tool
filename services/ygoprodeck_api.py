"""
YGOPRODeck API Client Service for searching cards, sets, and prices.
"""
import time
import asyncio
from typing import List, Optional, Tuple, Dict
import httpx
from models import CardSearchResult, CardSetInfo, CardPrices
from config import YGOPRODECK_BASE_URL, API_RATE_LIMIT_DELAY


class YGOProDeckAPI:
    def __init__(self, base_url: str = YGOPRODECK_BASE_URL):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=10.0)
        self.last_request_time = 0.0
        self._sets_cache: Optional[List[Dict[str, str]]] = None

    async def _rate_limit(self):
        """Ensure rate limit (e.g., 20 req/sec = max 1 request every 0.05s)."""
        elapsed = time.time() - self.last_request_time
        if elapsed < API_RATE_LIMIT_DELAY:
            await asyncio.sleep(API_RATE_LIMIT_DELAY - elapsed)
        self.last_request_time = time.time()

    async def get_all_sets(self) -> List[Dict[str, str]]:
        """Fetch list of all card sets (code -> name mapping). Cached in memory."""
        if self._sets_cache is not None:
            return self._sets_cache
        
        await self._rate_limit()
        try:
            resp = await self.client.get("https://db.ygoprodeck.com/api/v7/cardsets.php")
            if resp.status_code == 200:
                self._sets_cache = resp.json()
                return self._sets_cache
        except Exception as e:
            print(f"Error fetching sets: {e}")
        return []

    async def search_cards(self, query: str) -> List[CardSearchResult]:
        """
        Search cards by passcode ID, set code (e.g. RA01-EN001, LOB-001), or card name (fuzzy/fname).
        """
        query = query.strip()
        if not query:
            return []

        # 1. If query is digits, try exact Passcode / ID
        if query.isdigit():
            results = await self.get_card_by_id(int(query))
            if results:
                return results

        # 2. Check if query resembles a Set Code (e.g. RA01-EN001, LOB-001, RA01-IT001, LOB-E001)
        # Standard Yu-Gi-Oh set code format: [SET_PREFIX]-[LANG][NUMBER] or [SET_PREFIX]-[NUMBER]
        # Handle user typing dots instead of dashes (e.g. SDMM.IT014 -> SDMM-IT014)
        query_for_set = query.replace(".", "-")
        if "-" in query_for_set:
            parts = query_for_set.split("-")
            prefix = parts[0].upper().strip() # e.g. RA01 or LOB
            
            # Fetch set list to map prefix (e.g. RA01 or LOB) to full set_name (e.g. "25th Anniversary Rarity Collection")
            all_sets = await self.get_all_sets()
            matching_set_names = [
                s["set_name"] for s in all_sets
                if s.get("set_code", "").upper() == prefix
            ]

            cards_found: List[CardSearchResult] = []
            for set_name in matching_set_names:
                cards = await self.get_cards_by_set_name(set_name)
                # Filter cards that contain the query set_code in their card_sets list
                for card in cards:
                    # check if card has set_code matching query (case-insensitive)
                    for cs in card.card_sets:
                        if cs.set_code.upper() == query_for_set.upper() or cs.set_code.upper().startswith(query_for_set.upper()):
                            if card not in cards_found:
                                cards_found.append(card)
                            break

            if cards_found:
                return cards_found

        # 3. Try exact name match or fuzzy name search (fname)
        await self._rate_limit()
        try:
            # Try fuzzy search with fname
            resp = await self.client.get(self.base_url, params={"fname": query})
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                return [self._parse_card_json(item) for item in data]
        except Exception as e:
            print(f"Error searching cards by fname: {e}")

        return []

    async def get_card_by_id(self, card_id: int) -> List[CardSearchResult]:
        """Fetch card details by passcode ID."""
        await self._rate_limit()
        try:
            resp = await self.client.get(self.base_url, params={"id": card_id})
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                return [self._parse_card_json(item) for item in data]
        except Exception as e:
            print(f"Error fetching card by ID: {e}")
        return []

    async def get_cards_by_set_name(self, set_name: str) -> List[CardSearchResult]:
        """Fetch all cards in a given set by set_name."""
        await self._rate_limit()
        try:
            resp = await self.client.get(self.base_url, params={"cardset": set_name})
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                return [self._parse_card_json(item) for item in data]
        except Exception as e:
            print(f"Error fetching cards by set: {e}")
        return []

    def _parse_card_json(self, data: dict) -> CardSearchResult:
        """Parse raw API card dict into CardSearchResult model."""
        card_sets = []
        for cs in data.get("card_sets", []):
            card_sets.append(CardSetInfo(
                set_name=cs.get("set_name", ""),
                set_code=cs.get("set_code", ""),
                set_rarity=cs.get("set_rarity", ""),
                set_rarity_code=cs.get("set_rarity_code", ""),
                set_price=str(cs.get("set_price", "0"))
            ))

        card_prices = []
        for cp in data.get("card_prices", []):
            try:
                cm_price = float(cp.get("cardmarket_price", 0.0))
            except (ValueError, TypeError):
                cm_price = 0.0
            try:
                tcg_price = float(cp.get("tcgplayer_price", 0.0))
            except (ValueError, TypeError):
                tcg_price = 0.0

            card_prices.append(CardPrices(
                cardmarket_price=cm_price,
                tcgplayer_price=tcg_price,
                ebay_price=float(cp.get("ebay_price", 0.0) or 0.0),
                amazon_price=float(cp.get("amazon_price", 0.0) or 0.0),
                coolstuffinc_price=float(cp.get("coolstuffinc_price", 0.0) or 0.0),
            ))

        return CardSearchResult(
            id=data.get("id"),
            name=data.get("name"),
            type=data.get("type", "Unknown"),
            desc=data.get("desc", ""),
            race=data.get("race"),
            attribute=data.get("attribute"),
            card_sets=card_sets,
            card_prices=card_prices
        )

    async def close(self):
        """Close httpx client session."""
        await self.client.aclose()
