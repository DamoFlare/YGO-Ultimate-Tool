"""
Configuration settings for Yu-Gi-Oh! TCG Valuer application.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root, if present; never overrides real env vars

# Web server (FastAPI) — bind to localhost only, this process holds the CardTrader token and
# reads/writes local files, it must never be reachable from the network.
WEB_HOST = "127.0.0.1"
WEB_PORT = 8000

# API Configuration
YGOPRODECK_BASE_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
API_RATE_LIMIT_DELAY = 0.05  # Delay between requests to respect 20 req/sec limit

# CardTrader marketplace API (https://www.cardtrader.com/en/docs/api/full/reference)
# Real, live marketplace listings — used as the primary price source, replacing YGOPRODeck's
# set_price/cardmarket_price (undocumented origin, not tied to a specific printing/condition).
# Credentials are read from .env (never commit real tokens) — see .env.example.
CARDTRADER_TOKEN = os.getenv("CARDTRADER_TOKEN", "")
CARDTRADER_BASE_URL = "https://api.cardtrader.com/api/v2"
CARDTRADER_YUGIOH_GAME_ID = 4  # confirmed live via GET /games
CARDTRADER_RATE_LIMIT_DELAY = 0.1  # conservative; real limit is 200 req/10s (10 req/s on /marketplace/products)

# Maps our NM/EX/GD/LP/PO buckets to CardTrader's condition strings (properties_hash.condition).
# "Mint" is folded into NM since our scale has no separate tier above Near Mint.
CARDTRADER_CONDITION_MAP = {
    "NM": ["Mint", "Near Mint"],
    "EX": ["Slightly Played"],
    "GD": ["Moderately Played"],
    "LP": ["Played"],
    "PO": ["Poor"],
}

# Reverse of CARDTRADER_CONDITION_MAP for SELLING (services/cardtrader_api.py create_listing):
# POST /products needs exactly one CardTrader condition string per bucket, not a list of
# acceptable-on-read values.
CARDTRADER_SELL_CONDITION = {
    "NM": "Near Mint",
    "EX": "Slightly Played",
    "GD": "Moderately Played",
    "LP": "Played",
    "PO": "Poor",
}

# Languages selectable when creating a listing (services/cardtrader_api.py create_listing's
# `language` param -> CardTrader's `yugioh_language` product property). NOT derived from
# CollectionItem.set_code's language suffix: YGOPRODeck's search only ever returns English set
# data during Add Card (see .claude/06-notes-and-discrepancies.md), so a set_code like "RA01-EN001"
# does not reliably reflect which language the user's physical copy actually is — the sell
# staging UI lets the user pick it explicitly per row instead.
CARDTRADER_SELL_LANGUAGES = [
    ("it", "Italian"),
    ("en", "English"),
    ("fr", "French"),
    ("de", "German"),
    ("es", "Spanish"),
]
DEFAULT_SELL_LANGUAGE = "it"  # this collection is entirely Italian physical copies

# Suggested listing price = CollectionItem.get_price_for_condition(condition) * (1 - this), shown
# as an editable pre-filled value in the sell staging form (web/routers/sell.py) whenever a
# condition is selected/pre-selected — undercutting the app's own displayed value to price
# competitively against existing real listings, never enforced (the price field stays editable).
SELL_SUGGESTED_PRICE_DISCOUNT = 0.10

# Local listing lifecycle (services/storage.py `listings` table) — our own bookkeeping state,
# never sent to or read from CardTrader directly.
LISTING_STATUS_ACTIVE = "active"
LISTING_STATUS_SOLD = "sold"
LISTING_STATUS_CANCELLED = "cancelled"

# Cardmarket Condition Multipliers (Cardmarket Standards) — fallback estimate used only when
# CardTrader has no real marketplace listing for a given condition (see CollectionItem.get_price_for_condition).
CONDITION_MULTIPLIERS = {
    "NM": 1.00,   # Near Mint (100%)
    "EX": 0.88,   # Excellent (~85-90%)
    "GD": 0.725,  # Good (~70-75%)
    "LP": 0.55,   # Light Played / Played (~50-60%)
    "PO": 0.35,   # Poor (~30-40%)
}

CONDITION_NAMES = {
    "NM": "Near Mint",
    "EX": "Excellent",
    "GD": "Good",
    "LP": "Light Played",
    "PO": "Poor"
}

# Storage Defaults
# DEFAULT_COLLECTION_FILE is the legacy JSON store — the running app no longer reads it directly
# (see services/storage.py, SQLite-backed), only scripts/migrate_to_sqlite.py does, and it's left
# on disk untouched afterward as a manual backup.
DEFAULT_COLLECTION_FILE = Path("collection.json")
DEFAULT_COLLECTION_DB_FILE = Path("collection.db")
DEFAULT_CSV_EXPORT_FILE = Path("collection.csv")
# Grading "pending" inbox (cards analyzed but not yet linked to a collection item) — persisted
# separately from collection.json since it holds base64-encoded photos, not collection data.
DEFAULT_PENDING_GRADINGS_FILE = Path("pending_gradings.json")

# --- Grading Module (Hybrid CV + VLM) ---

# Local Ollama server (see docker-compose.yml for the self-hosted setup)
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_VISION_MODEL = "llava"

# Geometric Agent — image processing tunables (services/grading/geometric_agent.py)
# NOTE: the card outline is no longer auto-detected — the user crops it manually in the web UI
# (drags the 4 corners over the uploaded photo) and normalize_card_image() just perspective-warps
# those user-supplied points. Several rounds of automatic detection (Canny, HSV saturation, shape
# validation, border-expansion) all still cropped imprecisely on some real photos — see
# "Cronologia: indagine precisione CV" in .CLAUDE/07-grading.md for the full history.
NORMALIZED_CARD_WIDTH = 750
NORMALIZED_CARD_HEIGHT = 1047  # standard TCG card ratio 63mm x 88mm
CARD_GRAYSCALE_WHITENESS_THRESHOLD = 180.0  # grayscale value (0-255) above which a pixel counts
                                             # as "whitened" (chipped black border/corner exposing
                                             # the white cardstock beneath) — an absolute physical
                                             # threshold, not a color-distance-to-reference one, so
                                             # it needs no reference ring and isn't thrown off by a
                                             # directional light source. Shared by edge wear and
                                             # corner whitening below.
EDGE_WEAR_BORDER_PX = 5             # outer perimeter strip inspected for whitening
EDGE_WEAR_SKIN_PX = 2               # pixels closest to the crop boundary skipped: the perspective
                                     # warp in normalize_card_image() leaves a couple of blended/
                                     # anti-aliased pixels right at the boundary that would
                                     # otherwise be misread as whitening
CORNER_ROI_PX = 50                  # size (px) of the square ROI inspected at each of the 4 corners
CENTERING_FRAME_AREA_RATIO_RANGE = (0.55, 0.95)  # expected print-frame area vs. full card area
CENTERING_FALLBACK_SUBGRADE = 7.0  # used when the print frame can't be confidently detected

# Geometric Agent thresholds
# Centering: worst-axis deviation from perfect 50/50, in percentage points, mapped to a 1-10 subgrade.
CENTERING_DEVIATION_TO_SUBGRADE = [
    (2.0, 10.0),
    (5.0, 9.0),
    (7.5, 8.0),
    (10.0, 7.0),
    (15.0, 6.0),
    (20.0, 5.0),
    (25.0, 4.0),
    (30.0, 3.0),
    (40.0, 2.0),
]
CENTERING_MIN_SUBGRADE = 1.0

# Edges: % of the thin border perimeter flagged as whitened, mapped to a 1-10 subgrade.
EDGE_WEAR_PCT_TO_SUBGRADE = [
    (2.0, 10.0),
    (5.0, 9.0),
    (10.0, 8.0),
    (15.0, 7.0),
    (25.0, 6.0),
    (35.0, 5.0),
    (50.0, 4.0),
    (65.0, 3.0),
    (80.0, 2.0),
]
EDGE_WEAR_MIN_SUBGRADE = 1.0

# Corners: % of the 4 corner ROIs flagged as whitened, mapped to a 1-10 subgrade. Same ladder
# shape as edge wear (same underlying measurement, just a different region) — not yet validated
# against real photos of worn corners, see .CLAUDE/07-grading.md.
CORNER_WHITENESS_PCT_TO_SUBGRADE = [
    (2.0, 10.0),
    (5.0, 9.0),
    (10.0, 8.0),
    (15.0, 7.0),
    (25.0, 6.0),
    (35.0, 5.0),
    (50.0, 4.0),
    (65.0, 3.0),
    (80.0, 2.0),
]
CORNER_MIN_SUBGRADE = 1.0

# Surface: VLM-reported defect severity mapped to a 1-10 subgrade.
SEVERITY_TO_SUBGRADE = {
    "none": 10.0,
    "light": 7.0,
    "heavy": 3.0,
}
UNKNOWN_SEVERITY_FALLBACK_SUBGRADE = 7.0  # used if the VLM returns an unexpected severity string

# Final grade = weighted average of the 4 subgrades, then capped at min(subgrades) + 1.0
# (BGS-style: a single bad subgrade drags the overall grade down), rounded to the nearest 0.5.
# Surface defects are weighted highest since they most affect perceived/resale value; centering
# is weighted lowest since minor miscentering rarely changes a card's market condition bucket.
# Corners was added after centering/edges/surface were already weighted 20/30/50 — rather than
# picking a fresh split by feel, the original three were scaled down proportionally (x0.8) to
# make room for corners at 0.20, preserving their relative weighting. Not validated against real
# graded cards, see .CLAUDE/07-grading.md.
GRADE_SUBGRADE_WEIGHTS = {
    "centering": 0.16,
    "edges": 0.24,
    "corners": 0.20,
    "surface": 0.40,
}

# Maps the final 1-10 grade onto the existing NM/EX/GD/LP/PO market condition buckets so a
# graded card's estimated value can be computed with the pricing already in CONDITION_MULTIPLIERS.
GRADE_TO_CONDITION = [
    (8.5, "NM"),
    (7.0, "EX"),
    (5.5, "GD"),
    (4.0, "LP"),
]
GRADE_TO_CONDITION_FALLBACK = "PO"

# System prompt sent to the VLM Inspector Agent. Do not tweak the JSON schema (the key names and
# types) without updating services/grading/ai_agent.py's parsing accordingly — the "details"
# field's requested length/content can be adjusted freely, it's free text.
INSPECTOR_SYSTEM_PROMPT = (
    "You are an expert trading card grading assistant specializing in Yu-Gi-Oh! cards. Your "
    "ONLY task is to analyze the surface of the card provided. The image is perfectly cropped. "
    "DO NOT analyze the edges, borders, or centering. Focus entirely on the artwork, text box, "
    "and holographic foil. Look for scratches and creases. Respond ONLY with a valid JSON "
    "object using this schema: {\"has_scratches\": bool, \"scratch_severity\": \"none\" | "
    "\"light\" | \"heavy\", \"has_creases\": bool, \"crease_severity\": \"none\" | \"light\" | "
    "\"heavy\", \"details\": \"2-3 sentence description explaining exactly what you observed and "
    "roughly where on the card (e.g. top-left corner, center artwork, holographic foil), and how "
    "confident you are in that assessment\"}"
)
