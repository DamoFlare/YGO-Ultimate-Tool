"""
Configuration settings for Yu-Gi-Oh! TCG Valuer application.
"""
from pathlib import Path

# API Configuration
YGOPRODECK_BASE_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
API_RATE_LIMIT_DELAY = 0.05  # Delay between requests to respect 20 req/sec limit

# Cardmarket Condition Multipliers (Cardmarket Standards)
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
