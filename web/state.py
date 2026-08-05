"""
Shared application state for the web app — single-process, single-user, in-memory.

Mirrors what used to live as instance attributes on the Textual App (the retired ui/app.py):
one shared YGOProDeckAPI/CardTraderAPI/StorageService/CardGrader instance, the collection loaded
once at startup and mutated in place, plus the transient state needed by the two multi-step
flows (Bulk Add's queue, Grading's last analyzed result). No per-user sessions — a deliberate
simplification for this single-user local tool, see .CLAUDE/06-note-e-discrepanze.md.
"""
import base64
import io
from typing import Dict, List, Optional

from PIL import Image

from models import CardSearchResult, CardSetInfo, CollectionItem, GradingResult
from services.cardtrader_api import CardTraderAPI
from services.grading.grader import CardGrader, DebugImages
from services.storage import StorageService
from services.ygoprodeck_api import YGOProDeckAPI


class BulkQueueItem:
    """One entry in the Bulk Add queue — mirrors the dict used by the old BulkAddView."""

    def __init__(self, query: str, results: List[CardSearchResult]):
        self.query = query
        self.results = results
        self.added = False
        self.skipped = False


class AppState:
    """Single shared instance, created at FastAPI startup and closed at shutdown."""

    def __init__(self):
        self.api = YGOProDeckAPI()
        self.cardtrader = CardTraderAPI()
        self.storage = StorageService()
        self.grader = CardGrader()
        self.collection: List[CollectionItem] = self.storage.load_collection()

        # Bulk Add flow
        self.bulk_queue: List[BulkQueueItem] = []
        self.bulk_index: int = -1

        # Grading flow — the single most-recent analysis, referenced by "Save with Grade"
        self.last_grading_result: Optional[GradingResult] = None
        self.last_debug_images: Optional[DebugImages] = None

    async def add_card_to_collection(
        self,
        card: CardSearchResult,
        selected_set: Optional[CardSetInfo],
        qty: int = 1,
        grade: Optional[float] = None,
        condition: Optional[str] = None,
        grade_breakdown: Optional[Dict[str, float]] = None,
    ) -> CollectionItem:
        """
        Port of the old ui/app.py add_card_to_collection_logic — identical merge/pricing rules.
        Does NOT persist to disk (matches the old behavior): the caller decides when to save,
        since Bulk Add stages several of these in memory before a single final commit.
        """
        set_code = selected_set.set_code if selected_set else "PROMO"
        set_name = selected_set.set_name if selected_set else ""
        rarity = selected_set.set_rarity if selected_set else "Standard"

        # Pricing comes exclusively from CardTrader's real marketplace listings — YGOPRODeck is
        # only used for card lookup/search, never for prices.
        base_price = 0.0
        real_prices = await self.cardtrader.find_real_prices(set_code, rarity)
        price_source = None
        if real_prices:
            price_source = "cardtrader"
            if "NM" in real_prices:
                base_price = real_prices["NM"]

        # Graded copies never merge into (or with) a differently-graded/ungraded stack.
        existing_item = next(
            (
                item for item in self.collection
                if item.id == card.id and item.set_code == set_code and item.rarity == rarity
                and item.grade == grade
            ),
            None,
        )

        if existing_item:
            existing_item.quantity += qty
            existing_item.base_price = base_price
            existing_item.real_condition_prices = real_prices
            existing_item.price_source = price_source
            return existing_item

        new_item = CollectionItem(
            id=card.id,
            name=card.name,
            set_code=set_code,
            set_name=set_name,
            rarity=rarity,
            base_price=base_price,
            quantity=qty,
            grade=grade,
            condition=condition,
            grade_breakdown=grade_breakdown,
            real_condition_prices=real_prices,
            price_source=price_source,
        )
        self.collection.append(new_item)
        return new_item

    async def close(self) -> None:
        await self.api.close()
        await self.cardtrader.close()
        await self.grader.close()


def image_to_data_uri(image: Image.Image) -> str:
    """Encode a PIL Image as a base64 PNG data URI, embeddable directly in an <img src=...>."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
