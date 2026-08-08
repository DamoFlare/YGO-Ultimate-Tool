"""
One-off migration: collection.json -> collection.db (SQLite).

Run manually from the project root:
    python scripts/migrate_to_sqlite.py

collection.json is never modified or deleted — it's left on disk as a backup. Unlike
StorageService.load_collection() (which silently degrades to an empty list on any error, a
permissive contract that's fine for the running app but wrong for a migration), this script
aborts loudly with a clear message on any problem: missing source file, malformed JSON, a row
that fails CollectionItem validation, or a destination that already has data.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from models import CollectionItem
from services.storage import StorageService


def main():
    json_path = config.DEFAULT_COLLECTION_FILE
    db_path = config.DEFAULT_COLLECTION_DB_FILE

    if not json_path.exists():
        print(f"Error: {json_path} not found — nothing to migrate.")
        sys.exit(1)

    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: {json_path} is not valid JSON: {e}")
        sys.exit(1)

    items = []
    for i, entry in enumerate(raw):
        try:
            items.append(CollectionItem(**entry))
        except Exception as e:
            print(f"Error: row {i} in {json_path} failed validation: {e}")
            sys.exit(1)

    # sqlite3.connect() creates an empty file just by connecting, so check for a pre-existing
    # destination with Path.exists() BEFORE opening any connection to it.
    if db_path.exists():
        import sqlite3
        conn = sqlite3.connect(db_path)
        try:
            table_exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='collection_items'"
            ).fetchone()
            count = 0
            if table_exists:
                count = conn.execute("SELECT COUNT(*) FROM collection_items").fetchone()[0]
        finally:
            conn.close()
        if count > 0:
            print(
                f"Error: {db_path} already contains {count} row(s); refusing to import to avoid "
                f"duplicating data. Remove or rename {db_path} first if you really want to re-run this."
            )
            sys.exit(1)

    storage = StorageService(db_path=db_path)
    if not storage.save_collection(items):
        print("Error: migration failed while writing to the database (see error above).")
        sys.exit(1)

    print(f"Migrated {len(items)} card(s) from {json_path} to {db_path}.")
    print(f"{json_path} has been left untouched as a backup.")


if __name__ == "__main__":
    main()
