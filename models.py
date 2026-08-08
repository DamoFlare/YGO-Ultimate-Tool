"""
Data models for Yu-Gi-Oh! TCG Valuer.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from config import CONDITION_MULTIPLIERS


class CardSetInfo(BaseModel):
    """Information about a specific set printing of a card."""
    set_name: str
    set_code: str
    set_rarity: str
    set_rarity_code: Optional[str] = ""
    set_price: Optional[str] = "0"


class CardPrices(BaseModel):
    """Base prices from external sources (Cardmarket, TCGPlayer, etc.)."""
    cardmarket_price: float = 0.0
    tcgplayer_price: float = 0.0
    ebay_price: float = 0.0
    amazon_price: float = 0.0
    coolstuffinc_price: float = 0.0


class CollectionItem(BaseModel):
    """Represents an item stored in the user's collection."""
    # SQLite surrogate primary key (services/storage.py) — None until first persisted. Not part
    # of business identity (see id/set_code/rarity/grade, used for merge/lookup/delete), exists
    # so future features (e.g. marketplace listings) can reference a specific stack stably.
    row_id: Optional[int] = None
    id: int                              # Passcode / YGOPRODeck ID
    name: str                            # English Name
    set_code: str                        # Specific set code (e.g. RA01-EN001)
    set_name: Optional[str] = ""         # Set Name (e.g. 25th Anniversary Rarity Collection)
    rarity: str                          # Rarity (e.g. Ultra Rare)
    base_price: float = 0.0              # Cardmarket NM base/trend price
    quantity: int = 1                    # Quantity in collection
    added_at: Optional[str] = None       # ISO date added

    # Populated by the Grading module (services/grading/). None means "ungraded", which keeps
    # this item behaving exactly as before (assumed NM) for pricing and stack-merging purposes.
    grade: Optional[float] = None        # Final 1-10 grade from the hybrid CV+VLM grader
    condition: Optional[str] = None      # Grade mapped onto NM/EX/GD/LP/PO (config.GRADE_TO_CONDITION)
    grade_breakdown: Optional[Dict[str, float]] = None  # {"centering": .., "edges": .., "surface": ..}

    # Populated by services/cardtrader_api.py — the only price source in this app (YGOPRODeck is
    # used solely for card lookup/search, never for prices). A missing bucket means no active
    # CardTrader listing was found for that specific condition (falls back to estimating it from
    # the real NM price via CONDITION_MULTIPLIERS); real_condition_prices=None entirely means no
    # CardTrader match was found at all, so base_price stays 0.0 (unknown, not estimated).
    real_condition_prices: Optional[Dict[str, float]] = None  # e.g. {"NM": 15.89, "EX": 12.4}
    price_source: Optional[str] = None   # "cardtrader" if matched, else None (no real price known)

    # Resolved once by services/cardtrader_api.py's blueprint-matching logic (see
    # resolve_blueprint_for_sale) and then persisted forever — unlike real_condition_prices/
    # price_source (which find_real_prices happily re-resolves on every refresh, tolerating a
    # wrong match since the cost is just a slightly-off displayed price), a blueprint match
    # decides which physical printing gets promised to a real buyer when selling, so it is
    # resolved/disambiguated once and never silently re-guessed afterward.
    cardtrader_blueprint_id: Optional[int] = None
    cardtrader_blueprint_image_url: Optional[str] = None

    def get_price_for_condition(self, condition: str) -> float:
        """Real CardTrader marketplace price for this condition if known, else an estimate."""
        condition = condition.upper()
        if self.real_condition_prices and condition in self.real_condition_prices:
            return round(self.real_condition_prices[condition], 2)
        mult = CONDITION_MULTIPLIERS.get(condition, 1.0)
        return round(self.base_price * mult, 2)

    @property
    def condition_prices(self) -> Dict[str, float]:
        """Dictionary of prices for all condition grades."""
        return {
            cond: self.get_price_for_condition(cond)
            for cond in CONDITION_MULTIPLIERS.keys()
        }

    @property
    def total_nm_price(self) -> float:
        """Total price for NM condition multiplied by quantity."""
        return round(self.base_price * self.quantity, 2)

    @property
    def effective_price(self) -> float:
        """Price for the item's actual graded condition, or the NM price if ungraded."""
        if self.condition:
            return self.get_price_for_condition(self.condition)
        return round(self.base_price, 2)

    @property
    def total_effective_price(self) -> float:
        """effective_price multiplied by quantity."""
        return round(self.effective_price * self.quantity, 2)


class GradingResult(BaseModel):
    """Output of the hybrid CV + VLM card grading pipeline (services/grading/grader.py)."""
    # Geometric Agent (OpenCV) raw measurements
    centering_ratio: Dict[str, float] = Field(default_factory=dict)  # e.g. {"horizontal": 55.0, "vertical": 50.0}
    edge_wear_pct: float = 0.0
    corner_whitening_pct: float = 0.0

    # Inspector Agent (VLM) raw response
    surface_details: Dict[str, Any] = Field(default_factory=dict)  # raw parsed JSON from the VLM

    # Computed 1-10 subgrades
    centering_subgrade: float = 0.0
    edges_subgrade: float = 0.0
    corners_subgrade: float = 0.0
    surface_subgrade: float = 0.0

    # Final result
    final_grade: float = 0.0
    condition: str = "PO"
    explanation: str = ""  # deterministic "why this grade" narrative, see grader._build_explanation


class CardSearchResult(BaseModel):
    """Result from searching YGOPRODeck API."""
    id: int
    name: str
    type: str
    desc: str
    race: Optional[str] = None
    attribute: Optional[str] = None
    card_sets: List[CardSetInfo] = Field(default_factory=list)
    card_prices: List[CardPrices] = Field(default_factory=list)


class Listing(BaseModel):
    """
    One local record of a CardTrader marketplace listing (services/storage.py, `listings` table).
    Bookkeeping only — creating/cancelling a Listing never changes CollectionItem.quantity; the
    two are reconciled only by the user via /sell/poll-orders (see web/routers/sell.py), a known
    limitation (no CardTrader webhooks exist, see .claude/06-note-e-discrepanze.md).
    """
    id: Optional[int] = None                     # SQLite PK, None until first persisted
    collection_row_id: int                       # FK -> CollectionItem.row_id (not DB-enforced)
    cardtrader_blueprint_id: int
    cardtrader_product_id: Optional[int] = None   # CardTrader's own id, set once create succeeds
    condition: str                                # NM/EX/GD/LP/PO bucket actually listed
    language: str = "it"                          # CardTrader yugioh_language code actually listed
    price_eur: float
    quantity: int
    status: str = "active"                        # config.LISTING_STATUS_*
    created_at: str                               # ISO timestamp
    updated_at: str                               # ISO timestamp
    sold_at: Optional[str] = None
    error_message: Optional[str] = None
