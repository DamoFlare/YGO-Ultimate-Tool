"""
Storage service for reading, writing, and exporting Yu-Gi-Oh! collection data.

Collection data lives in a SQLite database (collection.db). save_collection() is always called
with the FULL current in-memory list (see web/state.py's AppState.collection) and is expected to
persist a snapshot of it — not to perform row-level diffing itself. To keep row_id stable across
saves (required so a future feature can reference a specific stack via a foreign key), it upserts
by row_id rather than blindly deleting and re-inserting everything: a naive delete-all/insert-all
would hand out fresh AUTOINCREMENT ids on every single save, since save_collection() runs after
nearly every mutation (add, refresh-prices, delete, bulk save-all, grading link).
"""
import csv
import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from models import CollectionItem, Listing
from config import DEFAULT_COLLECTION_DB_FILE, DEFAULT_CSV_EXPORT_FILE

_COLUMNS = [
    "id", "name", "set_code", "set_name", "rarity", "base_price", "quantity",
    "added_at", "grade", "condition", "grade_breakdown", "real_condition_prices",
    "price_source", "cardtrader_blueprint_id", "cardtrader_blueprint_image_url",
]

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS collection_items (
    row_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    id                      INTEGER NOT NULL,
    name                    TEXT NOT NULL,
    set_code                TEXT NOT NULL,
    set_name                TEXT,
    rarity                  TEXT NOT NULL,
    base_price              REAL NOT NULL DEFAULT 0.0,
    quantity                INTEGER NOT NULL DEFAULT 1,
    added_at                TEXT,
    grade                   REAL,
    condition               TEXT,
    grade_breakdown         TEXT,
    real_condition_prices   TEXT,
    price_source            TEXT,
    cardtrader_blueprint_id         INTEGER,
    cardtrader_blueprint_image_url  TEXT
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_collection_items_identity
    ON collection_items (id, set_code, rarity, grade)
"""

# Additive migration for DBs created before the sell feature (SQLite has no
# "ADD COLUMN IF NOT EXISTS" — must check PRAGMA table_info first). No-op on fresh DBs, where
# _CREATE_TABLE_SQL above already declares these columns.
_NEW_COLLECTION_COLUMNS = {
    "cardtrader_blueprint_id": "INTEGER",
    "cardtrader_blueprint_image_url": "TEXT",
}


def _ensure_collection_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(collection_items)").fetchall()}
    for col, sqltype in _NEW_COLLECTION_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE collection_items ADD COLUMN {col} {sqltype}")


_CREATE_LISTINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS listings (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_row_id        INTEGER NOT NULL,
    cardtrader_blueprint_id  INTEGER NOT NULL,
    cardtrader_product_id    INTEGER,
    condition                TEXT NOT NULL,
    language                 TEXT NOT NULL DEFAULT 'it',
    price_eur                REAL NOT NULL,
    quantity                 INTEGER NOT NULL,
    status                   TEXT NOT NULL DEFAULT 'active',
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    sold_at                  TEXT,
    error_message            TEXT
)
"""
# No FOREIGN KEY declared: this app never sets PRAGMA foreign_keys, so a declared-but-unenforced
# constraint would be misleading. Referential integrity against collection_items.row_id is instead
# enforced procedurally in web/routers/collection.py's delete route (see plan/KB).

_CREATE_LISTINGS_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_listings_collection_row_id ON listings (collection_row_id)",
    "CREATE INDEX IF NOT EXISTS idx_listings_status ON listings (status)",
]

# Additive migration, same reasoning as _ensure_collection_columns: no-op on fresh DBs where
# _CREATE_LISTINGS_TABLE_SQL above already declares this column.
_NEW_LISTINGS_COLUMNS = {"language": "TEXT NOT NULL DEFAULT 'it'"}


def _ensure_listings_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()}
    for col, sqltype in _NEW_LISTINGS_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {sqltype}")


_LISTING_COLUMNS = [
    "collection_row_id", "cardtrader_blueprint_id", "cardtrader_product_id", "condition",
    "language", "price_eur", "quantity", "status", "created_at", "updated_at", "sold_at",
    "error_message",
]


def _listing_to_row(listing: Listing) -> tuple:
    return (
        listing.collection_row_id, listing.cardtrader_blueprint_id, listing.cardtrader_product_id,
        listing.condition, listing.language, listing.price_eur, listing.quantity, listing.status,
        listing.created_at, listing.updated_at, listing.sold_at, listing.error_message,
    )


def _row_to_listing(row: sqlite3.Row) -> Listing:
    return Listing(
        id=row["id"],
        collection_row_id=row["collection_row_id"],
        cardtrader_blueprint_id=row["cardtrader_blueprint_id"],
        cardtrader_product_id=row["cardtrader_product_id"],
        condition=row["condition"],
        language=row["language"],
        price_eur=row["price_eur"],
        quantity=row["quantity"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        sold_at=row["sold_at"],
        error_message=row["error_message"],
    )


def _item_to_row(item: CollectionItem) -> tuple:
    """Serialize a CollectionItem into the _COLUMNS tuple order (dict fields -> JSON text)."""
    return (
        item.id, item.name, item.set_code, item.set_name, item.rarity,
        item.base_price, item.quantity, item.added_at, item.grade, item.condition,
        json.dumps(item.grade_breakdown) if item.grade_breakdown is not None else None,
        json.dumps(item.real_condition_prices) if item.real_condition_prices is not None else None,
        item.price_source, item.cardtrader_blueprint_id, item.cardtrader_blueprint_image_url,
    )


def _row_to_item(row: sqlite3.Row) -> CollectionItem:
    """Deserialize a DB row into a CollectionItem (JSON text -> dict fields)."""
    return CollectionItem(
        row_id=row["row_id"],
        id=row["id"],
        name=row["name"],
        set_code=row["set_code"],
        set_name=row["set_name"],
        rarity=row["rarity"],
        base_price=row["base_price"],
        quantity=row["quantity"],
        added_at=row["added_at"],
        grade=row["grade"],
        condition=row["condition"],
        grade_breakdown=json.loads(row["grade_breakdown"]) if row["grade_breakdown"] is not None else None,
        real_condition_prices=json.loads(row["real_condition_prices"]) if row["real_condition_prices"] is not None else None,
        price_source=row["price_source"],
        cardtrader_blueprint_id=row["cardtrader_blueprint_id"],
        cardtrader_blueprint_image_url=row["cardtrader_blueprint_image_url"],
    )


class StorageService:
    def __init__(self, db_path: Path = DEFAULT_COLLECTION_DB_FILE, csv_path: Path = DEFAULT_CSV_EXPORT_FILE):
        self.db_path = Path(db_path)
        self.csv_path = Path(csv_path)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(_CREATE_TABLE_SQL)
            _ensure_collection_columns(conn)
            conn.execute(_CREATE_INDEX_SQL)
            conn.execute(_CREATE_LISTINGS_TABLE_SQL)
            _ensure_listings_columns(conn)
            for stmt in _CREATE_LISTINGS_INDEX_SQL:
                conn.execute(stmt)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def load_collection(self) -> List[CollectionItem]:
        """Load all collection items from SQLite, ordered by row_id (insertion order)."""
        try:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT row_id, " + ", ".join(_COLUMNS) + " FROM collection_items ORDER BY row_id"
                ).fetchall()
                return [_row_to_item(row) for row in rows]
            finally:
                conn.close()
        except Exception as e:
            print(f"Error loading collection: {e}")
            return []

    def save_collection(self, collection: List[CollectionItem]) -> bool:
        """
        Persist the full given list as a snapshot: upsert every item by row_id (assigning a
        fresh one via INSERT for new items, backfilled onto the item in place), then prune any
        row not present in the given list. Preserves row_id across saves for existing items.
        """
        try:
            conn = self._connect()
            try:
                conn.execute("BEGIN")

                kept_row_ids = []
                placeholders = ", ".join("?" for _ in _COLUMNS)
                set_clause = ", ".join(f"{col} = ?" for col in _COLUMNS)

                for item in collection:
                    values = _item_to_row(item)
                    if item.row_id is not None:
                        cursor = conn.execute(
                            f"UPDATE collection_items SET {set_clause} WHERE row_id = ?",
                            values + (item.row_id,),
                        )
                        if cursor.rowcount == 0:
                            # Defensive fallback: row_id set on the item but missing from the
                            # table (shouldn't happen in normal operation) — insert fresh rather
                            # than silently dropping the item.
                            cursor = conn.execute(
                                f"INSERT INTO collection_items ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
                                values,
                            )
                            item.row_id = cursor.lastrowid
                        kept_row_ids.append(item.row_id)
                    else:
                        cursor = conn.execute(
                            f"INSERT INTO collection_items ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
                            values,
                        )
                        item.row_id = cursor.lastrowid
                        kept_row_ids.append(item.row_id)

                if kept_row_ids:
                    placeholders_ids = ", ".join("?" for _ in kept_row_ids)
                    conn.execute(
                        f"DELETE FROM collection_items WHERE row_id NOT IN ({placeholders_ids})",
                        kept_row_ids,
                    )
                else:
                    conn.execute("DELETE FROM collection_items")

                conn.execute("COMMIT")
                return True
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
        except Exception as e:
            print(f"Error saving collection: {e}")
            return False

    def load_listings(self, status: Optional[str] = None) -> List[Listing]:
        """All listings, optionally filtered by status, ordered by id."""
        try:
            conn = self._connect()
            try:
                query = "SELECT id, " + ", ".join(_LISTING_COLUMNS) + " FROM listings"
                params: tuple = ()
                if status is not None:
                    query += " WHERE status = ?"
                    params = (status,)
                query += " ORDER BY id"
                rows = conn.execute(query, params).fetchall()
                return [_row_to_listing(row) for row in rows]
            finally:
                conn.close()
        except Exception as e:
            print(f"Error loading listings: {e}")
            return []

    def get_active_listing_for_row(self, collection_row_id: int) -> Optional[Listing]:
        """The idempotency check used before staging/creating a new listing for a stack."""
        try:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT id, " + ", ".join(_LISTING_COLUMNS) + " FROM listings "
                    "WHERE collection_row_id = ? AND status = 'active' LIMIT 1",
                    (collection_row_id,),
                ).fetchone()
                return _row_to_listing(row) if row else None
            finally:
                conn.close()
        except Exception as e:
            print(f"Error checking active listing for row {collection_row_id}: {e}")
            return None

    def create_listing(self, listing: Listing) -> Optional[Listing]:
        """INSERT one listing, backfilling listing.id from lastrowid (mirrors save_collection's
        row_id backfill). Returns the same object, or None on failure."""
        try:
            conn = self._connect()
            try:
                placeholders = ", ".join("?" for _ in _LISTING_COLUMNS)
                cursor = conn.execute(
                    f"INSERT INTO listings ({', '.join(_LISTING_COLUMNS)}) VALUES ({placeholders})",
                    _listing_to_row(listing),
                )
                listing.id = cursor.lastrowid
                conn.commit()
                return listing
            finally:
                conn.close()
        except Exception as e:
            print(f"Error creating listing: {e}")
            return None

    def update_listing(self, listing: Listing) -> bool:
        """UPDATE ... WHERE id = ? — used for cancel (status->cancelled) and order polling
        (status->sold, sold_at set). Caller is responsible for bumping updated_at first."""
        try:
            conn = self._connect()
            try:
                set_clause = ", ".join(f"{col} = ?" for col in _LISTING_COLUMNS)
                conn.execute(
                    f"UPDATE listings SET {set_clause} WHERE id = ?",
                    _listing_to_row(listing) + (listing.id,),
                )
                conn.commit()
                return True
            finally:
                conn.close()
        except Exception as e:
            print(f"Error updating listing {listing.id}: {e}")
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
                "total_effective_value",
                "price_source"
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
                        "total_effective_value": f"{item.total_effective_price:.2f}",
                        "price_source": item.price_source or "unavailable"
                    })
            return True
        except Exception as e:
            print(f"Error exporting to CSV: {e}")
            return False
