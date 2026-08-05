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
DEFAULT_COLLECTION_FILE = Path("collection.json")
DEFAULT_CSV_EXPORT_FILE = Path("collection.csv")

# --- Grading Module (Hybrid CV + VLM) ---

# Local Ollama server (see docker-compose.yml for the self-hosted setup)
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_VISION_MODEL = "llava"

# Geometric Agent — image processing tunables (services/grading/geometric_agent.py)
NORMALIZED_CARD_WIDTH = 750
NORMALIZED_CARD_HEIGHT = 1047  # standard TCG card ratio 63mm x 88mm
EDGE_WEAR_BORDER_PX = 8            # thin outer perimeter strip inspected for wear
EDGE_WEAR_REFERENCE_OFFSET_PX = 24  # inner ring used as the "expected border color" baseline
EDGE_WEAR_COLOR_DISTANCE_THRESHOLD = 40.0  # BGR distance beyond which a pixel counts as "worn"
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

# Edges: % of the thin border perimeter flagged as worn/damaged, mapped to a 1-10 subgrade.
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

# Surface: VLM-reported defect severity mapped to a 1-10 subgrade.
SEVERITY_TO_SUBGRADE = {
    "none": 10.0,
    "light": 7.0,
    "heavy": 3.0,
}
UNKNOWN_SEVERITY_FALLBACK_SUBGRADE = 7.0  # used if the VLM returns an unexpected severity string

# Final grade = weighted average of the 3 subgrades, then capped at min(subgrades) + 1.0
# (BGS-style: a single bad subgrade drags the overall grade down), rounded to the nearest 0.5.
# Surface defects are weighted highest since they most affect perceived/resale value; centering
# is weighted lowest since minor miscentering rarely changes a card's market condition bucket.
# NOTE: known scope limitation — real BGS also grades Corners separately; this system does not
# (neither the geometric agent nor the VLM prompt cover corner-specific wear). See
# .CLAUDE/07-grading.md.
GRADE_SUBGRADE_WEIGHTS = {
    "centering": 0.20,
    "edges": 0.30,
    "surface": 0.50,
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
