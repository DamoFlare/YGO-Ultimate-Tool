"""
Shared application state for the web app — single-process, single-user, in-memory.

Mirrors what used to live as instance attributes on the Textual App (the retired ui/app.py):
one shared YGOProDeckAPI/CardTraderAPI/StorageService/CardGrader instance, the collection loaded
once at startup and mutated in place, plus the transient state needed by the multi-step flows
(Bulk Add's queue, Grading's pending-gradings inbox — the latter persisted to
config.DEFAULT_PENDING_GRADINGS_FILE, see PendingGrading below). No per-user sessions — a
deliberate simplification for this single-user local tool, see .CLAUDE/06-note-e-discrepanze.md.
"""
import base64
import io
import json
from typing import Any, Dict, List, Optional

from PIL import Image

import config
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


class PendingGrading:
    """
    One analyzed-but-not-yet-linked graded card, awaiting a "Collega" action from the user
    (single-photo Grading and Bulk Grading both feed the same list — see .CLAUDE/07-grading.md).

    Persisted to config.DEFAULT_PENDING_GRADINGS_FILE (a plain JSON file, one entry per pending
    card, images embedded as base64 — same encoding as image_to_data_uri) so a server restart
    doesn't lose cards already photographed/cropped/analyzed but not yet linked to the
    collection. Kept in a separate file from collection.json rather than folded into it: this
    holds full-size photos (base64), collection.json holds only pricing/condition data — mixing
    them would make every collection save/load drag along megabytes of unrelated image data.
    """

    def __init__(self, pending_id: int, filename: str, result: GradingResult, debug_images: DebugImages):
        self.id = pending_id
        self.filename = filename
        self.result = result
        self.debug_images = debug_images

    def to_dict(self) -> Dict[str, Any]:
        # JPEG rather than PNG for the on-disk copy: these are photographs (not the sharp-edged
        # UI graphics PNG is good at), and lossless PNG made a single pending card ~4MB — with a
        # dozen or more queued from a bulk session before linking, that adds up fast. Quality 85
        # is visually indistinguishable for "is this the right card" reference purposes.
        return {
            "id": self.id,
            "filename": self.filename,
            "result": self.result.model_dump(),
            "original": image_to_data_uri(self.debug_images.original, fmt="JPEG", quality=85),
            "annotated": image_to_data_uri(self.debug_images.annotated, fmt="JPEG", quality=85),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PendingGrading":
        debug_images = DebugImages(
            original=data_uri_to_image(data["original"]),
            annotated=data_uri_to_image(data["annotated"]),
        )
        return cls(data["id"], data["filename"], GradingResult(**data["result"]), debug_images)


class SellStagingItem:
    """
    One row awaiting sale confirmation on the /sell page. In-memory only — unlike PendingGrading
    (which embeds expensive-to-recreate photos and is persisted to its own JSON file), a staged
    sell item is just a reference to an existing CollectionItem plus a price/condition/quantity
    the user hasn't confirmed yet, cheap to reconstruct — so a restart simply loses unconfirmed
    staging, mirroring bulk_queue's "cheap to redo" reasoning rather than pending_gradings' extra
    persistence machinery.
    """

    def __init__(self, staging_id: int, collection_row_id: int):
        self.id = staging_id
        self.collection_row_id = collection_row_id
        # Denormalized display fields, copied at staging time
        self.name: str = ""
        self.set_code: str = ""
        self.rarity: str = ""
        self.collection_quantity: int = 0
        # Blueprint resolution outcome (see CardTraderAPI.resolve_blueprint_for_sale)
        self.blueprint_id: Optional[int] = None
        self.blueprint_image_url: Optional[str] = None
        self.blueprint_name: Optional[str] = None
        self.candidates: List[dict] = []      # populated only while ambiguous
        # User-editable sale fields
        self.condition: str = ""              # "" = required, not yet chosen (never default to NM)
        self.price: Optional[float] = None
        self.quantity: int = 1
        # Not derived from set_code (unreliable — see config.DEFAULT_SELL_LANGUAGE), always
        # explicitly editable per row since YGOPRODeck search only ever surfaces English set
        # data even for physically non-English copies.
        self.language: str = config.DEFAULT_SELL_LANGUAGE
        # Status
        self.error: Optional[str] = None


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

        # Grading flow — every analyzed card (single-photo or bulk) lands here until the user
        # links it to a collection item (or discards it). Loaded from disk so a restart doesn't
        # lose cards already analyzed but not yet linked.
        self.pending_gradings: List[PendingGrading] = self._load_pending_gradings()
        self._pending_grading_counter: int = max((p.id for p in self.pending_gradings), default=0)

        # Sell flow — staged cards awaiting review/confirmation on the /sell page. Pure in-memory,
        # never persisted (see SellStagingItem docstring).
        self.sell_staging: List[SellStagingItem] = []
        self._sell_staging_counter: int = 0

    def _load_pending_gradings(self) -> List[PendingGrading]:
        path = config.DEFAULT_PENDING_GRADINGS_FILE
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [PendingGrading.from_dict(item) for item in data]
        except Exception as e:
            print(f"Error loading pending gradings: {e}")
            return []

    def _save_pending_gradings(self) -> None:
        path = config.DEFAULT_PENDING_GRADINGS_FILE
        try:
            data = [p.to_dict() for p in self.pending_gradings]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error saving pending gradings: {e}")

    def add_pending_grading(self, filename: str, result: GradingResult, debug_images: DebugImages) -> PendingGrading:
        self._pending_grading_counter += 1
        pending = PendingGrading(self._pending_grading_counter, filename, result, debug_images)
        self.pending_gradings.append(pending)
        self._save_pending_gradings()
        return pending

    def get_pending_grading(self, pending_id: int) -> Optional[PendingGrading]:
        return next((p for p in self.pending_gradings if p.id == pending_id), None)

    def remove_pending_grading(self, pending_id: int) -> bool:
        pending = self.get_pending_grading(pending_id)
        if pending is None:
            return False
        self.pending_gradings.remove(pending)
        self._save_pending_gradings()
        return True

    def add_staging_item(self, collection_row_id: int) -> SellStagingItem:
        self._sell_staging_counter += 1
        item = SellStagingItem(self._sell_staging_counter, collection_row_id)
        self.sell_staging.append(item)
        return item

    def get_staging_item(self, staging_id: int) -> Optional[SellStagingItem]:
        return next((s for s in self.sell_staging if s.id == staging_id), None)

    def remove_staging_item(self, staging_id: int) -> bool:
        item = self.get_staging_item(staging_id)
        if item is None:
            return False
        self.sell_staging.remove(item)
        return True

    def find_staging_item_by_row(self, collection_row_id: int) -> Optional[SellStagingItem]:
        return next((s for s in self.sell_staging if s.collection_row_id == collection_row_id), None)

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


def image_to_data_uri(image: Image.Image, fmt: str = "PNG", quality: Optional[int] = None) -> str:
    """Encode a PIL Image as a base64 data URI, embeddable directly in an <img src=...>. Default
    PNG (lossless, right for the live-session grading views); PendingGrading.to_dict() passes
    JPEG for the on-disk copy, where file size matters more than pixel-perfect fidelity."""
    buffer = io.BytesIO()
    save_kwargs = {"quality": quality} if quality is not None else {}
    image.convert("RGB").save(buffer, format=fmt, **save_kwargs) if fmt == "JPEG" else image.save(buffer, format=fmt)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    mime = "jpeg" if fmt == "JPEG" else fmt.lower()
    return f"data:image/{mime};base64,{encoded}"


def data_uri_to_image(data_uri: str) -> Image.Image:
    """Inverse of image_to_data_uri — used to reload PendingGrading images from disk."""
    encoded = data_uri.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(encoded)))
