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

    # Inspector Agent (VLM) raw response
    surface_details: Dict[str, Any] = Field(default_factory=dict)  # raw parsed JSON from the VLM

    # Computed 1-10 subgrades
    centering_subgrade: float = 0.0
    edges_subgrade: float = 0.0
    surface_subgrade: float = 0.0

    # Final result
    final_grade: float = 0.0
    condition: str = "PO"


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
