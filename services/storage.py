"""
Storage service for reading, writing, and exporting Yu-Gi-Oh! collection data.
"""
import json
import csv
from pathlib import Path
from typing import List
from models import CollectionItem
from config import DEFAULT_COLLECTION_FILE, DEFAULT_CSV_EXPORT_FILE, CONDITION_MULTIPLIERS


class StorageService:
    def __init__(self, json_path: Path = DEFAULT_COLLECTION_FILE, csv_path: Path = DEFAULT_CSV_EXPORT_FILE):
        self.json_path = Path(json_path)
        self.csv_path = Path(csv_path)

    def load_collection(self) -> List[CollectionItem]:
        """Load collection items from JSON file."""
        if not self.json_path.exists():
            return []
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [CollectionItem(**item) for item in data]
        except Exception as e:
            print(f"Error loading collection: {e}")
            return []

    def save_collection(self, collection: List[CollectionItem]) -> bool:
        """Save collection items to JSON file."""
        try:
            data = [item.model_dump() for item in collection]
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving collection: {e}")
            return False

    def export_to_csv(self, collection: List[CollectionItem]) -> bool:
        """Export collection with condition price breakdowns to CSV."""
        try:
            fieldnames = [
                "id",
                "name",
                "set_code",
                "set_name",
                "rarity",
                "grade",
                "condition",
                "quantity",
                "base_price_NM",
                "price_EX",
                "price_GD",
                "price_LP",
                "price_PO",
                "total_NM_value",
                "total_effective_value"
            ]
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for item in collection:
                    writer.writerow({
                        "id": item.id,
                        "name": item.name,
                        "set_code": item.set_code,
                        "set_name": item.set_name,
                        "rarity": item.rarity,
                        "grade": f"{item.grade:.1f}" if item.grade is not None else "",
                        "condition": item.condition or "",
                        "quantity": item.quantity,
                        "base_price_NM": f"{item.base_price:.2f}",
                        "price_EX": f"{item.get_price_for_condition('EX'):.2f}",
                        "price_GD": f"{item.get_price_for_condition('GD'):.2f}",
                        "price_LP": f"{item.get_price_for_condition('LP'):.2f}",
                        "price_PO": f"{item.get_price_for_condition('PO'):.2f}",
                        "total_NM_value": f"{item.total_nm_price:.2f}",
                        "total_effective_value": f"{item.total_effective_price:.2f}"
                    })
            return True
        except Exception as e:
            print(f"Error exporting to CSV: {e}")
            return False
